# Changelog

## 0.1.0 — unreleased

First cut. Everything here is load-bearing; nothing is scaffolding.

### Added

- **Cross-sectional RankIC** with integer average ranks, per-date skipping of thin
  cross-sections, and a two-sided Student-t tail computed without scipy.
- **Newey-West t** with a bandwidth floored at the forward horizon, reported alongside
  the i.i.d. t so the autocorrelation correction is visible rather than silent.
- **Value fingerprint**: identity from the realised rank pattern, hashed as integers,
  invariant to monotone rewrites and to sign. Near-duplicates reported, never merged.
- **Expression canonicalisation** (8 conservative rules) — diagnostic only, never used
  to merge trials.
- **SQLite ledger** with an idempotent `(fp, panel_id, horizon)` key, WAL, retry on
  transient lock failures, and schema migration.
- **Selection threshold by block bootstrap** of the family's max |t|, with an adaptive
  number of replicates and a documented refusal to answer below 60 dates.
- **Verdict engine**: `LABEL_CONTAMINATION` > `INSUFFICIENT_DATA` > direction > FWER.
  Benjamini-Hochberg q-values reported, not gated on.
- **MCP server over stdio**, hand-rolled and dependency-free: `fingerprint`,
  `evaluate`, `gate`, `ledger_stats`. Strict JSON (non-finite → `null`).
- **95 tests**, including an eight-process concurrency test and a calibration pair
  (false-positive rate and power) that must both hold.
- Four demos: `noise_200`, `true_factor`, `leaky_momentum`, `equivalents`.

### Known limits

- The look-ahead check catches `factor == forward`, not subtler leaks. The
  perturbation protocol lands in 0.2.
- `PaperBroker`-style OOS locking is specified but not implemented.
- No data adapter yet: panels are the caller's problem.
