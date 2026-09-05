#!/usr/bin/env python3
"""End-to-end negative controls for usage normalization and candidate acceptance."""
import json
import runpy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class EfficiencyTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.directory = Path(self.scratch.name)

    def tearDown(self):
        self.scratch.cleanup()

    def audit(self, records):
        path = self.directory / 'session.jsonl'
        path.write_text(''.join(json.dumps(r) + '\n' for r in records))
        return subprocess.run([sys.executable, str(ROOT / 'scripts/session-audit.py'),
                               '--runtime', 'codex', '--transcripts', str(self.directory),
                               '--all', '--json'], capture_output=True, text=True)

    def event(self, total, last=None):
        return {'type': 'event_msg', 'payload': {'type': 'token_count', 'info': {
            'total_token_usage': total, 'last_token_usage': last or total}}}

    def usage(self, input=100, cached=60, write=10, output=20):
        return {'input_tokens': input, 'cached_input_tokens': cached,
                'cache_write_input_tokens': write, 'output_tokens': output,
                'reasoning_output_tokens': 0, 'total_tokens': input + output}

    def test_native_duplicate_counters_and_cache_subsets(self):
        first = self.event(self.usage())
        second = self.event(self.usage(250, 160, 10, 50), self.usage(150, 100, 0, 30))
        first['timestamp'] = '2026-09-06T00:00:00Z'
        second['timestamp'] = '2026-09-06T02:00:00Z'
        result = self.audit([first, first, {'type': 'token_usage_record', 'payload': {}}, second])
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report['request_count'], 2)
        self.assertEqual(report['token_totals'], {'input': 80, 'cache_read': 160,
                                                'cache_creation': 10, 'output': 50})
        self.assertEqual(report['context_per_request']['p90'], 150)
        self.assertEqual(report['idle'], {'gaps': None, 'cache_rebuilt_after': None})

    def test_native_missing_cache_category_stays_unknown(self):
        usage = self.usage()
        del usage['cache_write_input_tokens']
        result = self.audit([self.event(usage)])
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertIsNone(report['token_totals']['input'])
        self.assertIsNone(report['token_totals']['cache_creation'])
        self.assertEqual(report['context_per_request']['p90'], 100)

    def test_native_counter_reset_and_truncated_prefix_fail(self):
        first = self.event(self.usage())
        for records in ([first, self.event(self.usage(50, 20, 0, 10))],
                        [self.event(self.usage(250, 160, 10, 50), self.usage())]):
            result = self.audit(records)
            self.assertEqual(result.returncode, 2, result.stdout)
            self.assertRegex(result.stderr, 'reset|unobserved usage prefix')

    def test_native_duplicate_session_export_fails(self):
        records = [{'type': 'session_meta', 'payload': {'id': 'same-session'}}, self.event(self.usage())]
        (self.directory / 'duplicate.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in records))
        result = self.audit(records)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn('duplicate native session', result.stderr)

    def test_native_optional_subset_coverage_must_agree(self):
        first = self.usage()
        total = self.usage(250, 160, 10, 50)
        del first['cache_write_input_tokens']
        del total['cache_write_input_tokens']
        result = self.audit([self.event(first), self.event(total, self.usage(150, 100, 10, 30))])
        self.assertEqual(result.returncode, 2, result.stdout)

    def test_native_unclassified_total_is_not_silently_lost(self):
        last = self.usage(0, 0, 0, 0)
        last['total_tokens'] = 17210
        result = self.audit([self.event(self.usage()), self.event(self.usage(), last)])
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn('total tokens disagree', result.stderr)

    def gate(self, baseline, candidate, candidate_cost=50, baseline_cost=100):
        corpus = self.directory / 'corpus'
        for number, grade in enumerate(('easy', 'hard')):
            item = str(number)
            directory = corpus / item
            directory.mkdir(parents=True, exist_ok=True)
            (directory / 'pr.json').write_text(json.dumps({'grade': grade}))
            (directory / 'truth.json').write_text(json.dumps([
                {'file': 'app.py', 'lines': [10, 10], 'reviewed': True}]))
            for name, answers, cost in (('base', baseline, baseline_cost),
                                         ('candidate', candidate, candidate_cost)):
                run = self.directory / name / item
                run.mkdir(parents=True, exist_ok=True)
                if answers[number] is not None:
                    (run / 'verdict.md').write_text(answers[number])
                (run / 'session.json').write_text(json.dumps({'token_totals': {
                    'input': cost, 'cache_read': 0, 'cache_creation': 0, 'output': 0}}))
        return subprocess.run([sys.executable, str(ROOT / 'scripts/bench-score.py'),
            '--corpus', str(corpus), '--run', f'base={self.directory / "base"}',
            '--run', f'candidate={self.directory / "candidate"}',
            '--baseline', 'base', '--candidate', 'candidate', '--json'], capture_output=True, text=True)

    hit = '## FIX\n| Where |\n|---|\n| `app.py:10` |\n'
    miss = 'No findings.\n'

    def test_gate_accepts_equal_quality_lower_cost(self):
        result = self.gate([self.hit, self.hit], [self.hit, self.hit])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['acceptance_gate']['passed'])

    def test_gate_rejects_cheaper_misses_and_missing_verdict(self):
        for answers in ([self.hit, self.miss], [self.hit, None]):
            with self.subTest(answers=answers):
                # Every run gets an isolated directory so a previous verdict cannot survive.
                with tempfile.TemporaryDirectory() as location:
                    self.directory = Path(location)
                    result = self.gate([self.hit, self.hit], answers)
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def test_gate_rejects_grade_regression_even_when_overall_ties(self):
        result = self.gate([self.miss, self.hit], [self.hit, self.miss])
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        reasons = json.loads(result.stdout)['acceptance_gate']['reasons']
        self.assertTrue(any('grade:hard' in reason for reason in reasons))

    def test_gate_rejects_unknown_and_nonfinite_cost(self):
        for value in (None, float('nan'), float('inf')):
            result = self.gate([self.hit, self.hit], [self.hit, self.hit], value)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def test_gate_rejects_nonfinite_aggregates(self):
        result = self.gate([self.hit, self.hit], [self.hit, self.hit], 1e307, 1e308)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def test_gate_cost_comparison_is_not_rounded(self):
        result = self.gate([self.hit, self.hit], [self.hit, self.hit], 100.01, 100.04)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_empty_gate_names_do_not_disable_the_gate(self):
        result = self.gate([self.hit, self.hit], [self.hit, self.hit])
        result = subprocess.run(result.args + ['--baseline', '', '--candidate', ''],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)

    def test_gate_rejects_unpruned_items(self):
        result = self.gate([self.hit, self.hit], [self.hit, self.hit])
        (self.directory / 'corpus/1/truth.json').write_text('[{"reviewed": false}]')
        result = subprocess.run(result.args, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('unpruned corpus items', result.stdout)

    def test_gate_quality_comparison_is_not_rounded(self):
        module = runpy.run_path(str(ROOT / 'scripts/bench-score.py'))
        runs = []
        for name, matched, cost in [('base', 100000, 100), ('candidate', 99999, 50)]:
            overall = module['metric'](100000, 100000, matched)
            overall.update(tokens_per_review=cost, tokens_per_review_median=cost)
            runs.append({'name': name, 'items': [], 'grades': {}, 'overall': overall})
        self.assertEqual(runs[0]['overall']['f1'], runs[1]['overall']['f1'])
        self.assertFalse(module['acceptance_gate'](runs, 'base', 'candidate')['passed'])


if __name__ == '__main__':
    unittest.main()
