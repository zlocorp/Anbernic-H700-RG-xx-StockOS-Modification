# Durable recovery reconstruction

Goal: replace process-local installation retry with a durable journal. Reconstructed from requirements; not the missing original commit.

Architecture: a versioned JSON journal beside installed.json records running before executing any script and completed after successful return. Only completed operations may retry metadata. The uninstall script is embedded in the journal, so volatile staging may disappear. Unknown/corrupt state blocks mutations. One pending operation at a time; no automatic rollback or multiprocess support.

- [x] Reproduce restart loss with stdlib unittest, extracting only pure manager/data classes to avoid installer import-time hardware/network effects.
- [x] Add atomic journal save/load with fsync; persist before script start and before metadata finalization.
- [x] Test install/uninstall restart, lost staging, corrupt/ambiguous state, failed writes, stale catalog, unrelated records, repeated metadata failures and successful paths.
- [x] Run complete available test discovery, syntax compilation, independent review.
- [x] Save local commit, patch and Git bundle outside checkout; verify bundle. Never push.

Review focus: script completion/persistence gap; premature journal deletion; volatile staging; database read failures; UI retry after catalog refresh. Power-loss guarantees depend on the filesystem honoring fsync. Nonzero/timeout scripts require manual reconciliation because partial side effects cannot be inferred safely.

Verification: 19 stdlib unit tests pass; original 12 tests failed on baseline before implementation. Independent review identified late-generated uninstall.sh; fixed and regression-tested. Missing/offline catalog recovery and newer catalog version were also tested. No on-device SDL or physical power-loss validation performed. Backup status is recorded in the sibling artifact manifest.
