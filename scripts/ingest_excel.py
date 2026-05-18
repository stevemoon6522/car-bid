#!/usr/bin/env python3
"""ingest_excel.py — Parse Excel sheet '이번주거래(누적)' and upsert into car_auctions.

Usage:
    python scripts/ingest_excel.py <path/to/file.xlsx> [--upsert]

Without --upsert the script runs in dry-run mode: parses and validates rows but
does not write to the database.

Environment variables required:
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY

Column mapping (0-indexed, sheet '이번주거래(누적)'):
    0  경매일자        auction_date
    1  차종            vehicle_class
    2  제작사          maker
    3  차명            car_name
    4  모델명          model_name
    5  차종(*)         full_title
    6  년식            year
    7  최초등록일      first_registered
    8  변속기          transmission
    9  엔진형식코드    engine_code
    10 배기량          engine_cc
    11 연료            fuel
    12 등급            grade
    13 색상            color
    14 주행거리        mileage_km
    15 검색구          search_category
    16 옵션            options
    17 상품구분        product_type
    18 사고품횟수      accident_count
    19 검사내용        inspection_notes
    20 시작가          start_price
    21 응찰가          bid_price
    22 낙찰금액VAT포함 final_price
    23 낙찰/유찰       status
    (col 24 is sometimes present but unused)
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
from datetime import date, datetime, timedelta
from typing import Optional

from dotenv import load_dotenv
from openpyxl import load_workbook
from supabase import create_client

load_dotenv()

SHEET_NAME = "이번주거래(누적)"
BATCH_SIZE = 500


def _text(value) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _int(value) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _date(value) -> Optional[str]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date().strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, int):
        # Excel serial date: days since 1899-12-30 (accounting for the 1900 leap-year bug).
        try:
            return (datetime(1899, 12, 30) + timedelta(days=value)).date().strftime("%Y-%m-%d")
        except Exception:
            return None
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
            try:
                return datetime.strptime(value.strip(), fmt).strftime("%Y-%m-%d")
            except ValueError:
                pass
    return None


def _compute_hash(auction_date, car_name, model_name, year, mileage_km, grade, color, final_price) -> str:
    """Compute a row hash that distinguishes None from empty string using a NULL sentinel (\0)."""
    parts = [auction_date, car_name, model_name, year, mileage_km, grade, color, final_price]
    norm = [("\x00" if p is None else str(p)) for p in parts]
    raw = "|".join(norm)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def parse_row(row_values: list) -> Optional[dict]:
    """Convert a list of cell values into a DB-ready dict.

    Returns None if the row lacks car_name, model_name, or status (header/empty rows).
    """
    if len(row_values) < 24:
        # Pad with None so index access doesn't raise.
        row_values = list(row_values) + [None] * (24 - len(row_values))

    car_name = _text(row_values[3])
    model_name = _text(row_values[4])
    status = _text(row_values[23])

    if not car_name or not model_name or not status:
        return None
    # Skip header-like rows where car_name is the literal column name.
    if car_name == "차명":
        return None

    auction_date = _date(row_values[0])
    grade = _text(row_values[12])
    color = _text(row_values[13])
    mileage_km = _int(row_values[14])
    final_price = _int(row_values[22])
    year = _int(row_values[6])

    grade_first: Optional[str] = None
    if grade and len(grade) >= 1 and grade[0].upper() in "ABCDF":
        grade_first = grade[0].upper()

    is_outlier = False
    if mileage_km is not None:
        is_outlier = mileage_km < 100 or mileage_km > 500_000

    row_hash = _compute_hash(
        auction_date, car_name, model_name, year, mileage_km, grade, color, final_price
    )

    first_registered = _date(row_values[7])

    return {
        "auction_date": auction_date,
        "vehicle_class": _text(row_values[1]),
        "maker": _text(row_values[2]),
        "car_name": car_name,
        "model_name": model_name,
        "full_title": _text(row_values[5]),
        "year": year,
        "first_registered": first_registered,
        "transmission": _text(row_values[8]),
        "engine_code": _text(row_values[9]),
        "engine_cc": _int(row_values[10]),
        "fuel": _text(row_values[11]),
        "grade": grade,
        "color": color,
        "mileage_km": mileage_km,
        "search_category": _text(row_values[15]),
        "options": _text(row_values[16]),
        "product_type": _text(row_values[17]),
        "accident_count": _int(row_values[18]),
        "inspection_notes": _text(row_values[19]),
        "start_price": _int(row_values[20]),
        "bid_price": _int(row_values[21]),
        "final_price": final_price,
        "status": status,
        "grade_first": grade_first,
        "is_outlier": is_outlier,
        "row_hash": row_hash,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest Excel auction data into Supabase car_auctions table.")
    parser.add_argument("path", help="Path to the .xlsx file")
    parser.add_argument("--upsert", action="store_true", help="Write to DB (default: dry-run)")
    args = parser.parse_args()

    supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

    if args.upsert and (not supabase_url or not service_key):
        print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set for --upsert mode.")
        sys.exit(1)

    sb = create_client(supabase_url, service_key) if args.upsert else None

    print(f"Opening workbook: {args.path}")
    wb = load_workbook(args.path, read_only=True, data_only=True)

    if SHEET_NAME not in wb.sheetnames:
        print(f"ERROR: Sheet '{SHEET_NAME}' not found. Available: {wb.sheetnames}")
        sys.exit(1)

    ws = wb[SHEET_NAME]
    print(f"Sheet found. Iterating rows...")

    parsed_count = 0
    skipped_count = 0
    batch: list[dict] = []
    upserted_count = 0
    dupe_count = 0
    warn_count = 0
    batches_ok = 0
    batches_fail = 0
    batch_index = 0

    def _flush_batch(b: list[dict]) -> None:
        nonlocal upserted_count, dupe_count, batches_ok, batches_fail, batch_index
        batch_index += 1
        if not sb:
            upserted_count += len(b)
            batches_ok += 1
            return
        try:
            resp = sb.table("car_auctions").upsert(b, on_conflict="row_hash", ignore_duplicates=True).execute()
            inserted = len(resp.data) if resp.data else 0
            dupes = len(b) - inserted
            upserted_count += inserted
            dupe_count += dupes
            batches_ok += 1
        except Exception as exc:
            first_hash = b[0].get("row_hash", "?") if b else "?"
            print(f"  [WARN] Batch {batch_index} FAILED (first row_hash={first_hash}): {exc}")
            batches_fail += 1

    for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        record = parse_row(list(row))
        if record is None:
            skipped_count += 1
            continue

        if record["auction_date"] is None:
            warn_count += 1
            skipped_count += 1
            continue

        parsed_count += 1
        batch.append(record)

        if len(batch) >= BATCH_SIZE:
            _flush_batch(batch)
            batch = []

        if parsed_count % 5000 == 0:
            print(f"  Parsed {parsed_count:,} rows so far...")

    # Flush remainder
    if batch:
        _flush_batch(batch)

    wb.close()

    total_batches = batches_ok + batches_fail

    print()
    print(f"=== Ingest complete ({'DRY-RUN' if not args.upsert else 'LIVE'}) ===")
    print(f"  Rows parsed:    {parsed_count:,}")
    print(f"  Rows skipped:   {skipped_count:,}  (empty/header)")
    print(f"  Warnings:       {warn_count:,}  (missing auction_date)")
    print(f"  Batches:        {batches_ok}/{total_batches} succeeded, {batches_fail} failed")
    if args.upsert:
        print(f"  Upserted (new): {upserted_count:,}")
        print(f"  Duplicates:     {dupe_count:,}  (ON CONFLICT DO NOTHING)")
        if dupe_count > parsed_count * 0.9:
            print("  [ALERT] More than 90% duplicates — check if this file was already ingested.")
        if batches_fail:
            print(f"  [ALERT] {batches_fail} batch(es) failed — some rows were NOT upserted.")


if __name__ == "__main__":
    main()
