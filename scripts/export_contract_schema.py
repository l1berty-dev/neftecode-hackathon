"""Regenerate the checked-in JSON Schema for the shared contract fixture."""

from __future__ import annotations

import json
from pathlib import Path

from neftecode_hackathon.api import create_app
from neftecode_hackathon.contracts import ContractExample

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_PATH = ROOT / "examples" / "contract_v1.synthetic.json"
SCHEMA_PATH = ROOT / "examples" / "contract_v1.schema.json"
OPENAPI_PATH = ROOT / "examples" / "openapi.v1.json"


def main() -> None:
    payload = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
    ContractExample.model_validate(payload)
    schema = ContractExample.model_json_schema()
    SCHEMA_PATH.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    OPENAPI_PATH.write_text(
        json.dumps(create_app().openapi(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
