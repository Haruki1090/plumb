"""Normalize scoped Codex cumulative usage snapshots without reading message text into reports."""


class CodexNormalizer:
    fields = ('input_tokens', 'cached_input_tokens', 'output_tokens',
              'cache_write_input_tokens', 'reasoning_output_tokens')

    def __init__(self):
        self.previous = None
        self.sequence = 0
        self.model = None
        self.session_id = None

    def counters(self, raw):
        if not isinstance(raw, dict):
            raise ValueError('missing native token usage object')
        result = {}
        for index, name in enumerate(self.fields):
            value = raw.get(name)
            if value is None and index >= 3:
                result[name] = None
                continue
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f'invalid native usage counter: {name}')
            result[name] = value
        if result['cached_input_tokens'] + (result['cache_write_input_tokens'] or 0) > result['input_tokens']:
            raise ValueError('native cache subsets exceed total input')
        if result['reasoning_output_tokens'] is not None and result['reasoning_output_tokens'] > result['output_tokens']:
            raise ValueError('native reasoning subset exceeds total output')
        if 'total_tokens' in raw and raw['total_tokens'] != result['input_tokens'] + result['output_tokens']:
            raise ValueError('native total tokens disagree with input plus output')
        return result

    def accept(self, record):
        kind = record.get('type')
        payload = record.get('payload')
        if not isinstance(payload, dict):
            return None
        if kind == 'session_meta':
            session_id = payload.get('id')
            if not isinstance(session_id, str) or not session_id:
                raise ValueError('missing native session identity')
            if self.session_id is not None and self.session_id != session_id:
                raise ValueError('multiple native sessions in one transcript')
            self.session_id = session_id
            return None
        if kind == 'turn_context':
            self.model = payload.get('model')
            return None
        if kind == 'response_item' and payload.get('type') in ('function_call_output', 'custom_tool_call_output'):
            return {'type': 'user', 'message': {'content': [
                {'type': 'tool_result', 'content': payload.get('output')}]}}
        if kind != 'event_msg':
            # Per-response token_usage_record duplicates the cumulative event stream.
            return None
        if payload.get('type') == 'task_started':
            return {'type': 'user', 'message': {'content': ''}}
        if payload.get('type') != 'token_count' or payload.get('info') is None:
            return None
        info = payload['info']
        if not isinstance(info, dict):
            raise ValueError('invalid native token_count info')
        total = self.counters(info.get('total_token_usage'))
        last = self.counters(info.get('last_token_usage'))
        for name in self.fields:
            if (total[name] is None) != (last[name] is None):
                raise ValueError(f'native total/last counter coverage disagrees: {name}')
        if total == self.previous:
            return None
        if self.previous is None:
            if total != last:
                raise ValueError('native transcript starts with an unobserved usage prefix')
        else:
            for name in self.fields:
                old, new = self.previous[name], total[name]
                if (old is None) != (new is None):
                    raise ValueError(f'native counter coverage changed: {name}')
                if new is not None and (new < old or new - old != last[name]):
                    raise ValueError(f'native counter reset or missing snapshot: {name}')
        self.previous = total
        self.sequence += 1
        cache_write = last['cache_write_input_tokens']
        uncached = (last['input_tokens'] - last['cached_input_tokens'] - cache_write
                    if cache_write is not None else None)
        return {
            'type': 'assistant', 'requestId': f'codex-{self.sequence}',
            'timestamp': record.get('timestamp'), '_native_context': last['input_tokens'],
            'message': {'model': self.model, 'usage': {
                'input_tokens': uncached, 'cache_read_input_tokens': last['cached_input_tokens'],
                'cache_creation_input_tokens': cache_write, 'output_tokens': last['output_tokens'],
                'output_tokens_details': {'thinking_tokens': last['reasoning_output_tokens']},
            }},
        }
