#!/usr/bin/env python3
"""Check a real S3 boot capture; does not simulate AFE or acoustic acceptance."""

import argparse
import json
import re
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("serial_log", type=Path)
    parser.add_argument("--initialization-only", action="store_true",
                        help="Check startup only, without claiming stream stability")
    parser.add_argument("--min-runtime-seconds", type=float, default=0,
                        help="Require this much time between first and last AFE telemetry")
    args = parser.parse_args()
    if args.min_runtime_seconds < 0:
        parser.error("minimum runtime must be nonnegative")
    log = args.serial_log.read_text(errors="replace")
    lines = log.splitlines()
    report_lines = [line for line in lines
                    if "s3_afe: feed=" in line and "feed_errors=" in line]
    reports = [
        dict(re.findall(r"(\w+)=([\d.]+)", line))
        for line in report_lines
    ]
    timestamp = re.compile(r"\b[VDIWE] \(\s*(\d+)\)")
    report_times = [int(m[1]) if (m := timestamp.search(line)) else None
                    for line in report_lines]
    log_times = [int(m[1]) for line in lines if (m := timestamp.search(line))]
    observed_seconds = None
    failures = []
    if "Local wake unavailable" in log or "local AFE initialization failed" in log:
        failures.append("AFE initialization failed")
    if "station_connected" not in log:
        failures.append("Wi-Fi did not connect")
    if "main_task: Returned from app_main()" not in log or not re.search(
        r"s3_afe: feed=\d+ x4 fetch=\d+ x1", log
    ):
        failures.append("AFE startup did not finish")
    if any(marker in log for marker in ("Guru Meditation", "assert failed:", "Stack canary watchpoint")):
        failures.append("firmware panicked")
    if not args.initialization_only and (not reports or not all(
        int(reports[-1][key]) > 0 for key in ("feed", "fetch")
    )):
        failures.append("no running AFE feed/fetch telemetry")
    if any(int(row[key]) for row in reports for key in ("feed_errors", "fetch_errors")):
        failures.append("AFE feed/fetch errors")
    if not args.initialization_only:
        if "AFE unavailable:" in log or "AFE reset failed:" in log:
            failures.append("AFE became unavailable")
        if len(reports) < 2:
            failures.append("need two telemetry reports to verify progress")
        else:
            pairs = list(zip(reports, reports[1:]))
            if any(int(after[key]) <= int(before[key])
                   for before, after in pairs for key in ("feed", "fetch")):
                failures.append("AFE counters did not advance")
            if any(int(after[key]) > int(before[key])
                   for before, after in pairs for key in ("rx_gaps", "resets")):
                failures.append("RX gaps or resets grew during observation")
            if any(int(after.get(key, 0)) > int(before.get(key, 0))
                   for before, after in pairs
                   for key in ("overruns", "missed_eof", "capture_overruns")):
                failures.append("capture drops grew during observation")
            if any(t is None for t in report_times):
                failures.append("need timestamped AFE telemetry")
            else:
                observed_seconds = (report_times[-1] - report_times[0]) / 1000
                # Reports are nominally 10s apart. Allow one additional period
                # for scheduling jitter, never minutes of unobserved silence.
                if any(not 0 < after - before <= 20000
                       for before, after in zip(report_times, report_times[1:])):
                    failures.append("AFE telemetry interval invalid or exceeded 20s")
                if log_times and max(log_times) - report_times[-1] > 20000:
                    failures.append("AFE telemetry stale at end of capture")
                if observed_seconds < args.min_runtime_seconds:
                    failures.append("AFE observation shorter than required minimum")
        if reports and "AFE discontinuity:" in log.rsplit("s3_afe: feed=", 1)[-1]:
            failures.append("RX discontinuity after last telemetry")
    print(json.dumps({"passed": not failures, "initialization_only": args.initialization_only,
                      "failures": failures,
                      "observed_runtime_seconds": observed_seconds,
                      "reports": len(reports), "last": reports[-1] if reports else None},
                     ensure_ascii=False, indent=2))
    return bool(failures)


if __name__ == "__main__":
    raise SystemExit(main())
