"""Regenerate the checked-in OpenAPI document without starting runtime services."""

from __future__ import annotations

import json
from pathlib import Path

from neftecode_hackathon.api import create_app

ROOT = Path(__file__).resolve().parents[1]
OPENAPI_PATH = ROOT / "examples" / "openapi.v1.json"


def main() -> None:
    OPENAPI_PATH.write_text(
        json.dumps(create_app().openapi(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
