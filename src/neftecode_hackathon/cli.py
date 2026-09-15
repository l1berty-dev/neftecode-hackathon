"""Command-line entry points for repository workflows."""

from __future__ import annotations

import argparse
import sys

from neftecode_hackathon.data import prepare_data
from neftecode_hackathon.quality import train_forecast


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="neftecode-hackathon")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("prepare", help="prepare and audit the provided historical data")
    subparsers.add_parser("train", help="train and evaluate the 60-minute continuation forecast")
    return parser


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
