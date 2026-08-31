---
name: principle-migrate-callers-then-delete-legacy-apis
origin: plumb
description: "Migrate the callers and delete the old API inside the same wave, instead of leaving a compatibility layer as the default. Use when rebuilding an internal API, or when you hear yourself say \"we can delete the old one later\", \"just add a shim for now\", or \"deprecate it and clean it up next quarter\"."
---

# Migrate callers then delete legacy APIs

**Once you have decided the new shape is right, put the caller migration and the deletion
of the old API in the same wave.** "Delete it later" never gets deleted.

**Why this is hard to keep.** Split the deletion into a pass of its own and that pass
**adds no feature and carries nothing but the risk of breaking something**. Asked to
justify itself, it goes to the back of the queue every time. Meanwhile the old API keeps
collecting new callers for as long as it stands. **Every deferral makes the next deletion
bigger.** A deadline will not hold this. Only the slicing holds it: **migration and
deletion in one wave.**

## What finishing it means

- **Count the callers first and write the number down.** If you have not counted, the
  migration has not started
- **Put the migration and the deletion in the same wave.** No old path survives the end
  of the wave
- **Rewrite the tests so they assert the new contract.** A test that only guards the
  internals of the old implementation goes out with the old API
- **If you leave an intermediate layer, write down what removes it and who removes it.**
  If you cannot write that, what you have is a permanent fork

## How to tell afterwards

**When the wave ends, a search for the old name returns zero hits.** Count more than the
code: tests, configuration, documents and comments. If it is not zero, write down on the
spot why the remainder was left.

## Where this does not apply

**This principle does not apply when consumers outside your reach depend on the old API.**
There, compatibility *is* the contract. **What this principle covers is the internal API
whose callers you can count, all of them, yourself.**

Refusing to treat a halfway migration as the target belongs to
**principle-outcome-oriented-execution**. What this principle owns is **the slicing**:
never split migration and deletion into separate waves.
