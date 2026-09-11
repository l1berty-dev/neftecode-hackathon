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
  values and units, canonical units only where the source unit is compatible, and quality issues.
- `events.parquet`: text, missing, invalid-timestamp, and non-finite source events. `Pt Created`
  is retained here and is never converted to zero.
- `data_dictionary.json`: source-to-signal mappings, descriptions, units, conversion policy,
  verification status, and evidence.
- `candidate_signals.json`: review candidates and their current verification status. It does not
  declare any process control available.
- `audit_report.json`: input hashes, dataset version, row/time coverage, duplicate and sampling
  checks, value ranges, anomaly counts, and LIMS delay sensitivity.
- `prepared_state_example.json`: a real replay-mode prepared state for integration handoff. It is
  deliberately not labeled as a `ProcessSnapshot`; route C adds the immutable snapshot contract.

## Data rules and assumptions

- Source timestamps have no offset. `Europe/Moscow` is the documented experimental source
  timezone; prepared timestamps are UTC.
- Default source availability delays are read from `config/model.yaml` and are currently zero.
  The report also shifts every LIMS `available_at` by 120 minutes as a sensitivity experiment.
  This is not a confirmed laboratory delay.
- LIMS is parsed as 54 independent date/value pairs under grouped sampling-point headers. PAK is
  parsed as independent A:B and D:E pairs; column C must stay empty.
- Source values are not removed because they look unusual. Exact `307` values are counted only.
  A value becomes `suspect` only through a named rule, such as a negative quantity described as a
  flow, an impossible percentage, or a source unit incompatible with its indicator.
- CSV telemetry units are not present in the supplied KIP dictionary. They remain null and
  unverified; short tag letters and numerical ranges are not used to invent units.
- PAK sulfur uses the documented mass-basis assumption `1 ppm = 1 mg/kg`. The original `ppm`
  label is retained and the dictionary marks the assumption explicitly.
- Dataset identity is a SHA-256 hash of all structured source files, the preparation module, and
  the effective data/time/availability settings. Re-running unchanged code, inputs, and settings
  produces the same version.
