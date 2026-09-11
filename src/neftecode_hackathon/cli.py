"""Command-line entry points for repository workflows."""

from __future__ import annotations

import argparse
import sys

from neftecode_hackathon.data import prepare_data


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="neftecode-hackathon")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("prepare", help="prepare and audit the provided historical data")
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
