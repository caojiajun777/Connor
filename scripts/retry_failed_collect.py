"""Retry failed account collects into an existing daily run.

Examples:
  python scripts/retry_failed_collect.py --latest --report-date 2026-07-23
  python scripts/retry_failed_collect.py --run-id <id> --passes 2
  python scripts/retry_failed_collect.py --run-id <id> --handles foo,bar
"""

from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Retry failed_retryable collects for a daily run")
    parser.add_argument("--run-id", default="", help="Existing run id")
    parser.add_argument("--latest", action="store_true", help="Use the most recent run")
    parser.add_argument(
        "--handles",
        default="",
        help="Comma-separated handles (default: failed_retryable / page_incomplete from run)",
    )
    parser.add_argument(
        "--report-date",
        default="",
        help="Pin CONNOR_COLLECT_REPORT_DATE (YYYY-MM-DD) for same-day cursor mint policy",
    )
    parser.add_argument("--accept-gap", action="store_true")
    parser.add_argument(
        "--no-accept-partial",
        action="store_true",
        help="Treat remaining soft failures as blocking (default: accept_partial)",
    )
    parser.add_argument(
        "--passes",
        type=int,
        default=1,
        help="How many iterative retry rounds (default: 1; ignored with --until-done)",
    )
    parser.add_argument(
        "--until-done",
        action="store_true",
        help="Wait interval between passes until all accounts succeed",
    )
    parser.add_argument(
        "--interval-sec",
        type=int,
        default=0,
        help="Seconds between retry passes (default: 900 / env)",
    )
    args = parser.parse_args(argv)

    from app.daily.retry_failed_collect import retry_failed_collect

    handles = [h.strip().lstrip("@") for h in str(args.handles).split(",") if h.strip()]
    until_done = bool(args.until_done)
    try:
        result = retry_failed_collect(
            run_id=str(args.run_id).strip() or None,
            latest=bool(args.latest),
            handles=handles or None,
            report_date=str(args.report_date).strip() or None,
            accept_gap=bool(args.accept_gap),
            accept_partial=not bool(args.no_accept_partial),
            max_passes=None if until_done else max(1, int(args.passes)),
            until_done=until_done,
            wait_before_first=until_done,
            interval_sec=int(args.interval_sec) or None,
        )
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, default=str))
    if result.remaining_failed:
        print(
            "\nStill failed: "
            + ",".join(result.remaining_failed)
            + "\nRe-run the same command after a short wait / IP cool-down.",
            file=sys.stderr,
        )
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
