"""Count user-reported action outcomes over an explicit window; no persistence."""

from __future__ import annotations

import json
import sys
from datetime import date


def parse_day(value: object) -> date:
    if not isinstance(value, str):
        raise ValueError("dates must be YYYY-MM-DD")
    try:
        day = date.fromisoformat(value)
    except ValueError:
        raise ValueError("dates must be YYYY-MM-DD") from None
    if day.isoformat() != value:
        raise ValueError("dates must be YYYY-MM-DD")
    return day


def summarize(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("expected an object")
    start, end = parse_day(payload.get("start_date")), parse_day(payload.get("end_date"))
    if not 0 <= (end - start).days < 366:
        raise ValueError("window must contain 1 to 366 calendar days")
    scheduled = payload.get("scheduled_dates")
    records = payload.get("records")
    if not isinstance(scheduled, list) or not 1 <= len(scheduled) <= 366:
        raise ValueError("provide 1 to 366 explicitly scheduled dates for one action")
    days = [parse_day(value) for value in scheduled]
    if len(set(days)) != len(days) or any(not start <= day <= end for day in days):
        raise ValueError("scheduled dates must be unique and inside the window")
    if not isinstance(records, list) or len(records) > 366:
        raise ValueError("records must be an array with at most 366 entries")
    counts = dict.fromkeys(("done", "partial", "not_done", "paused", "unknown"), 0)
    seen = set()
    for index, row in enumerate(records):
        if not isinstance(row, dict):
            raise ValueError(f"record {index}: expected an object")
        day = parse_day(row.get("date"))
        if day not in days or day in seen:
            raise ValueError(f"record {index}: date is unscheduled or duplicated")
        status = row.get("status")
        if not isinstance(status, str) or status not in counts:
            raise ValueError(f"record {index}: invalid status")
        counts[status] += 1
        seen.add(day)
    counts["unknown"] += len(days) - len(seen)
    return {
        "ok": True,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "scheduled_count": len(days),
        "reported_count": len(records),
        "counts": counts,
        "limitations": [
            "one_action_at_most_one_opportunity_per_date",
            "missing_reports_are_unknown_not_failure",
            "self_report_not_independent_verification",
            "no_health_outcome_or_state_transition_inferred",
        ],
    }


def main() -> int:
    if sys.argv[1:] == ["--help"]:
        print("JSON stdin: start_date,end_date,scheduled_dates,records[{date,status}]")
        return 0
    try:
        payload = json.load(sys.stdin) if not sys.argv[1:] else None
    except (ValueError, UnicodeError):
        print(json.dumps({"ok": False, "error": "expected valid UTF-8 JSON on stdin"}))
        return 2
    try:
        result = summarize(payload)
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
