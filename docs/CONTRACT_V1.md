# Contract version 1

This is the integration note for developer 2. The executable source of truth is
`src/neftecode_hackathon/contracts.py`; do not create parallel DTO definitions in the
scenario, orchestration, or persistence packages.

## Files to consume

- Pydantic models: `src/neftecode_hackathon/contracts.py`
- Quality-agent protocol: `src/neftecode_hackathon/quality/base.py`
- Synthetic end-to-end fixture: `examples/contract_v1.synthetic.json`
- Generated JSON Schema: `examples/contract_v1.schema.json`
- Shared model/data assumptions: `config/model.yaml`

The fixture is intentionally marked `synthetic: true`. Its values and action are not verified
industrial limits or setpoints. No real control is declared available by this contract work.

## Interface for scenario evaluation

```python
class QualityAgent(Protocol):
    def assess(
        self,
        snapshot: ProcessSnapshot,
        action: Action,
        horizon_minutes: int,
    ) -> QualityAssessment: ...
```

Developer 2 can implement a test double against this protocol inside `tests/`. Production code
must receive the quality agent through dependency injection and must not import test doubles.

## Contract decisions

- All public models are immutable and reject unknown fields.
- Datetimes must include an offset. Prepared data will be stored as UTC; source timestamps are
  interpreted as `Europe/Moscow` according to `config/model.yaml`.
- Public numeric fields reject NaN and infinity. Missing measurements use `value: null` together
  with `quality: missing`; anomalous sentinel-looking values are not silently converted.
- Signal IDs are namespaced, for example `ht:F26`, `avt:T33`, or
  `lab:ht.product_sulfur`.
- An action contains absolute new values, not deltas. An empty `changes` map means that current
  settings are retained.
- `unsupported` and `insufficient_data` quality assessments expose no forecast numbers.
- A decision validator requires one snapshot ID, horizon, model version, and constraint version
  across every included scenario.
- Trace entries are calculation audit records, not hidden reasoning or a simulated conversation.

## Verification

Regenerate the schema after a deliberate contract change:

```bash
uv run python scripts/export_contract_schema.py
```

Then run:

```bash
uv run pytest tests/test_contracts.py
```

Any contract change must update the fixture, generated schema, this note when relevant, and the
round-trip tests in the same change.
