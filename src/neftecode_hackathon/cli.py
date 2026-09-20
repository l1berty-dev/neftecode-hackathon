"""Command-line entry points for repository workflows."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

from neftecode_hackathon.data import prepare_data
from neftecode_hackathon.quality import train_forecast


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="neftecode-hackathon")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("prepare", help="prepare and audit the provided historical data")
    subparsers.add_parser("train", help="train and evaluate the 60-minute continuation forecast")
    evaluate = subparsers.add_parser(
        "evaluate", help="evaluate the shared decision cycle at an ISO replay timestamp"
    )
    evaluate.add_argument("--at", required=True, type=_aware_datetime, metavar="ISO_TIMESTAMP")
    subparsers.add_parser("serve", help="serve the versioned FastAPI application")
    return parser


def _aware_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise argparse.ArgumentTypeError("--at must be a valid ISO timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("--at must include a timezone offset")
    return parsed


def main(argv: list[str] | None = None) -> None:
    raw_args = sys.argv[1:] if argv is None else argv
    parser = build_parser()
    if not raw_args:
        parser.print_help()
        return
    args = parser.parse_args(raw_args)
    if args.command == "prepare":
        report = prepare_data(progress=print)
        print(f"Prepared dataset {report['dataset_version']}")
        print(
            "Rows: "
            f"telemetry={report['outputs']['telemetry_rows']}, "
            f"analyses={report['outputs']['analysis_rows']}, "
            f"events={report['outputs']['event_rows']}"
        )
    elif args.command == "train":
        result = train_forecast(progress=print)
        manifest = result["manifest"]
        metrics = result["metrics"]
        print(f"Trained model {manifest['model_version']}")
        print(
            f"Selected {manifest['selected_predictor']}; "
            f"validation MAE={metrics['validation']['selected']['mae']:.6g}; "
            f"test MAE={metrics['test']['selected']['mae']:.6g}"
        )
    elif args.command == "evaluate":
        from neftecode_hackathon.api.service import build_calculation_runtime

        decision = build_calculation_runtime().decide_at(args.at)
        print(json.dumps(decision.model_dump(mode="json"), ensure_ascii=False, indent=2))
    elif args.command == "serve":
        import uvicorn

        port = int(os.environ.get("API_PORT", "8000"))
        uvicorn.run(
            "neftecode_hackathon.api.app:app",
            host="127.0.0.1",
            port=port,
            workers=1,
        )
