# Data preparation and audit

The route-B pipeline reads the immutable files under `context/` and writes reproducible
derivatives under the Git-ignored `data/processed/` directory.

Run it from the repository root:

```bash
uv run neftecode-hackathon prepare
```

## Outputs

- `telemetry.parquet`: long-form AVT and 24-2000 telemetry. Signal IDs use `avt:` and `ht:`
  namespaces. Each row keeps measurement and availability timestamps, value, source, quality,
  issues, and the original column name.
- `analyses.parquet`: independent LIMS and PAK series with point IDs, original labels, original
  values and units, canonical units, named corrections, and quality issues.
- `events.parquet`: text, missing, invalid-timestamp, and non-finite source events. `Pt Created`
  is retained here and is never converted to zero.
- `data_dictionary.json`: source-to-signal mappings, descriptions, units, conversion policy,
  verification status, and evidence.
- `candidate_signals.json`: review candidates and their current verification status. It does not
  declare any process control available.
- `audit_report.json`: input hashes, dataset version, row/time coverage, duplicate and sampling
  checks, value ranges, anomaly counts, and LIMS delay sensitivity.
- `prepared_state_example.json`: a diagnostic latest-state summary. It is deliberately not labeled
  as a `ProcessSnapshot`; consumers must use `SnapshotProvider` for point-in-time state.

## Data rules and assumptions

- Source timestamps have no offset. `Europe/Moscow` is the documented experimental source
  timezone; prepared timestamps are UTC.
- Default source availability delays are read from `config/model.yaml`. LIMS timestamps are sample
  times, so the prepared dataset conservatively uses `available_at = measured_at + 240 minutes`.
  The audit compares that default with a shorter 120-minute sensitivity assumption; the shorter
  assumption is not written into the prepared series.
- LIMS is parsed as 54 independent date/value pairs under grouped sampling-point headers. PAK is
  parsed as independent A:B and D:E pairs; column C must stay empty.
- Source values are not removed because they look unusual. Exact `307` values are counted only.
  A value becomes `suspect` only through a named blocking rule, such as a negative quantity
  described as a flow or an impossible percentage. The four known wrong LIMS unit labels (`D15`,
  `EBP.T`, `50%.T`, `I350`) are corrected from the analyte name without rescaling; original labels,
  numeric values, correction reason, and organizer evidence remain in the outputs.
- Direct CSV-to-KIP tag correspondence is organizer-confirmed. CSV numeric units and scales are not
  supplied, so they remain null and unit-unverified; the old T6/P8 mapping suspicion is removed
  without inventing a scale.
- PAK sulfur uses the documented mass-basis assumption `1 ppm = 1 mg/kg`. The original `ppm`
  label is retained and the dictionary marks the assumption explicitly.
- Dataset identity is a SHA-256 hash of all structured source files, the preparation module, and
  the effective data/time/availability settings. Re-running unchanged code, inputs, and settings
  produces the same version.

## Point-in-time snapshots

`SnapshotProvider.from_repository().get_snapshot(t)` returns the shared immutable
`ProcessSnapshot` contract. It performs an independent backward as-of selection for every signal,
requires both `measured_at <= t` and `available_at <= t`, and includes the inclusive interval
`[t - 360 minutes, t]` in history. Freshness comes from `config/model.yaml`; completeness comes
only from an explicitly verified model-input manifest in developer 2's validated scenario policy.
After route D the manifest requires fresh valid `pak:ht.product_sulfur` in `mg/kg` with a maximum
age of 1200 seconds; snapshots before training or with a different policy remain fail-closed.

Optional `SourceConflictRule` objects allow a train/validation-derived threshold to mark two fresh
equivalent sources suspect. No real conflict threshold is configured before model training, and the
final test period must not be used to choose one.

The reproducible forecast workflow and actual holdout metrics are documented in
[`FORECAST_MODEL_V1.md`](FORECAST_MODEL_V1.md). Generated model and metric artifacts stay ignored
by Git and are recreated with `uv run neftecode-hackathon train`.
