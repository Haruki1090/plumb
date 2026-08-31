# Writing tests

**A test you never watched fail protects nothing.**

When you add new behavior, when you fix a bug, when you touch an existing test.
**"What has to pass for this to be done" is the spec; "which tests, written how" is the plan** —
that split of rank is owned by SKILL.md and `playbooks/writing-a-plan.md` and is not copied
here (**principle-encode-lessons-in-structure**). **What this playbook holds is the content of
the test itself.**

## 1. Make it fail first

**Write it before the implementation and watch it fail** (**principle-prove-it-works**).

What you watch is not "it failed" but **how it failed**.

- **Is it failing for the reason you expected?** A typo, a failed import, a broken environment:
  that is not red. Fix it and make it fail again
- **If it passed the moment you wrote it, all you did was transcribe behavior that already
  exists.** That test protects nothing. **Throw it away and write it again**

**A test written afterwards always passes on the first run.** Passing proves nothing about its
ability to fail. If you already wrote the implementation, **deleting the implementation before
you add the test** is the shortest path; leave it in place and you end up deriving the expected
values from the code you wrote.

## 2. Name what has to break for it to fail, before you write it

Say it in one sentence before you write the body: **"if X becomes Y, this test fails."**
A test you cannot say that about carries no information whether it passes or fails.

- **Is that X a defect, or a convention?** A test that fails only on the value of a constant,
  on wording, or on an internal shape **fails on every intentional change and sleeps through
  the real defects.** Watch the **behavior** that depends on the convention instead
- **Do not build the expected value out of the code under test.** If the same function computes
  both sides, they are equal whatever is inside. **Put down a hand-written value, or material
  you checked by hand**
- **Do not check a document or a script by searching its text.** Run it and look at the output,
  the side effects, the exit code. Text being text guarantees nothing
- **Do not retrace someone else's tool's specification.** What you verify is the contract of
  the surface you built. Only when you have stepped on unexpected behavior, put down one test
  that **names that assumption**

## 3. Name the tests that protect nothing, and forbid them

| Form | What is happening |
|---|---|
| **The whiff** | Nothing is checked. It fails only on an exception or a syntax error |
| **The mirror** | The expected value was built from the code under test. **It passes by definition** |
| **The transcript** | The implementation's internal structure was written down as-is. **Now it cannot be changed without breaking** |
| **The stand-in check** | It verifies the thing you swapped in. It passes while the stand-in is there and fails when you remove it. The real code is not involved |
| **The loosened test** | It would not pass, so the expectation came down. **The distance it came down is exactly the range it no longer protects** |

**Loosen only when you have judged the expectation to be wrong.**
When you do, **write down why it was wrong.** If you cannot write it, the implementation is
what needs fixing.

## 4. Run the real thing

**The only things you may swap out are the slow ones and the ones outside.**
Everything inside that line runs for real.

- **Before you swap something out, count what the real one does**: the writes, the defaults it
  fills in, the side effects. **Erase all of it and the checks that depended on it pass in
  silence**
- **Make what it returns carry as much as the real thing does.** A stand-in that holds only the
  fields you read starts lying the moment a later stage touches a field you did not.
  **The test stays green and it breaks in integration**
- **When setting the stand-in up runs longer than the body, stop using one.** Standing the real
  thing up is shorter and stronger
- **Do not grow test-only teardown on a production type.** If only tests call it, it is a test
  tool

## 5. Make it clear what broke when it fails

**Say the behavior in the name.** "works" and "case 1" are not names.
**When "and" shows up in a name, split it in two.** One test verifies one thing.

Check that the failure output **shows both the expected and the actual value.**
If it does not, whoever reads it later receives nothing but the fact that it failed.

## 6. Break something before you finish

**Break one place in the production code in your head and say which test fails.**
If nothing fails, that place is not protected.

- Change a constant or an argument to another value
- Invert a branch
- Delete a side effect or a state update
- Return empty or the default as-is
- Remove the check on empty, zero, unauthorized, or malformed input

**If nothing fails at all, either you add a test or one of them is a tautology.**

## Do not grow the count

**A test you do not need is a liability.** Do not write one for anything that carries no
production behavior — a bare getter, a bare pass-through, prose written for humans.
**A test written for the coverage number collects nothing but maintenance cost, forever.**

**What you return:** the tests you wrote and, one sentence each, the breakage each one catches.
**The evidence that you watched it fail** (the output while it was red) and the output after it
passed. The places you broke that nothing caught, and what you did about them.
