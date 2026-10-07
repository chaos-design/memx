"""Command-line entry point for the deterministic MemX evaluation suite."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional, Sequence

from .runner import (
    default_dataset_path,
    default_thresholds_path,
    load_eval_cases,
    load_thresholds,
    run_eval_suite,
    write_eval_report,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run MemX memory quality evals.")
    parser.add_argument("--dataset", default=str(default_dataset_path()))
    parser.add_argument("--thresholds", default=str(default_thresholds_path()))
    parser.add_argument("--output")
    parser.add_argument("--fail-on-regression", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    dataset_path = Path(args.dataset)
    report = run_eval_suite(
        load_eval_cases(dataset_path),
        load_thresholds(args.thresholds),
        dataset_name=dataset_path.name,
    )
    if args.output:
        write_eval_report(report, args.output)
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 1 if args.fail_on_regression and not report.passed else 0


if __name__ == "__main__":
    raise SystemExit(main())
