"""Describe selected weight records. JSON stdin/stdout; no files or network."""

from __future__ import annotations

import json
import math
import sys
from datetime import date, timedelta
from typing import Any


def summarize(payload: Any) -> dict[str, Any]:
    """Normalize explicit units and report arithmetic, never a health assessment."""
    records = payload.get("records") if isinstance(payload, dict) else None
    if not isinstance(records, list) or not 1 <= len(records) <= 366:
        raise ValueError("records must contain 1 to 366 selected records")

    rows: list[tuple[date, float]] = []
    seen: set[date] = set()
    for index, row in enumerate(records):
        if not isinstance(row, dict):
            raise ValueError(f"record {index}: expected an object")
        raw_date = row.get("date")
        try:
            day = date.fromisoformat(raw_date) if isinstance(raw_date, str) else None
        except ValueError:
            day = None
        if day is None or day.isoformat() != raw_date:
            raise ValueError(f"record {index}: date must be YYYY-MM-DD")
        if day in seen:
            raise ValueError(f"record {index}: duplicate date; select one record for that day")
        weight = row.get("weight")
        if (
            isinstance(weight, bool)
            or not isinstance(weight, (int, float))
            or not math.isfinite(weight)
            or weight <= 0
        ):
            raise ValueError(f"record {index}: weight must be a finite positive number")
        unit = row.get("unit")
        if unit not in ("kg", "lb"):
            raise ValueError(f"record {index}: explicit unit kg or lb is required")
        kilograms = weight if unit == "kg" else weight * 0.45359237
        seen.add(day)
        rows.append((day, kilograms))

    rows.sort()
    first_day, first_value = rows[0]
    last_day, last_value = rows[-1]
    windows = []
    for offset in (0, 7):
        end = last_day - timedelta(days=offset)
        start = end - timedelta(days=6)
        values = [weight for day, weight in rows if start <= day <= end]
        windows.append(
            {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "count": len(values),
                "mean_kg": round(sum(values) / len(values), 6) if values else None,
            }
        )
    return {
        "ok": True,
        "count": len(rows),
        "first_date": first_day.isoformat(),
        "last_date": last_day.isoformat(),
        "first_kg": round(first_value, 6),
        "last_kg": round(last_value, 6),
        "change_kg": round(last_value - first_value, 6) if len(rows) > 1 else None,
        "span_days": (last_day - first_day).days,
        "max_gap_days": max(
            ((right[0] - left[0]).days for left, right in zip(rows, rows[1:], strict=False)),
            default=0,
        ),
        "windows_anchored_to_last_record": windows,
        "limitations": [
            "user_supplied_records_not_independently_verified",
            "same_person_and_measurement_conditions_require_user_confirmation",
            "descriptive_arithmetic_only_no_health_or_body_fat_conclusion",
            "no_missing_day_imputation",
        ],
    }


def main() -> int:
    if sys.argv[1:] == ["--help"]:
        print('JSON stdin: {"records":[{"date":"YYYY-MM-DD","weight":70,"unit":"kg"}]}')
        return 0
    if sys.argv[1:]:
        print(json.dumps({"ok": False, "error": "use JSON stdin; no positional arguments"}))
        return 2
    try:
        payload = json.load(sys.stdin)
    except (ValueError, UnicodeError):
        # Do not echo a JSON parser's input into logs.
        print(json.dumps({"ok": False, "error": "expected valid UTF-8 JSON on stdin"}))
        return 2
    try:
        result = summarize(payload)
    except ValueError as exc:
        # summarize raises fixed messages with an index, never the raw record.
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2
    except OverflowError:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "record numbers or dates exceed the supported calculation range",
                }
            )
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
