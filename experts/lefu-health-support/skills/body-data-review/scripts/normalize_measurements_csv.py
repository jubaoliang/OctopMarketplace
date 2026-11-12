"""Normalize an explicitly selected weight CSV from stdin; never read files."""

from __future__ import annotations

import csv
import io
import json
import sys

from summarize_measurements import summarize


def normalize(text: str) -> dict:
    """Accept only date,weight,unit; reject ambiguity instead of guessing."""
    reader = csv.reader(io.StringIO(text.removeprefix("\ufeff")), strict=True)
    try:
        header = next(reader, None)
        if header is None or sorted(header) != ["date", "unit", "weight"]:
            raise ValueError("header must contain exactly date,weight,unit")
        rows = []
        for index, cells in enumerate(reader):
            if len(cells) != 3:
                raise ValueError(f"record {index}: expected three cells")
            row = dict(zip(header, cells, strict=True))
            try:
                weight = float(row["weight"])
            except ValueError:
                raise ValueError(f"record {index}: weight must be numeric") from None
            rows.append({"date": row["date"], "weight": weight, "unit": row["unit"]})
            if len(rows) > 366:
                raise ValueError("at most 366 selected records are supported")
    except csv.Error:
        raise ValueError("invalid CSV quoting or row structure") from None
    # Reuse the calculator's date, unit, duplicate and finite-number checks.
    summarize({"records": rows})
    rows.sort(key=lambda row: row["date"])
    return {"records": rows}


def main() -> int:
    if sys.argv[1:] == ["--help"]:
        print("CSV stdin: date,weight,unit; dates YYYY-MM-DD; units kg or lb")
        return 0
    try:
        if sys.argv[1:]:
            raise ValueError("use CSV stdin; no positional arguments")
        result = normalize(sys.stdin.read())
    except (ValueError, OverflowError, UnicodeError) as exc:
        message = str(exc) if type(exc) is ValueError else "unsupported input encoding or range"
        print(json.dumps({"ok": False, "error": message}))
        return 2
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
