"""db.py — Supabase client wrapper for car auction data.

Uses service-role key; RLS deny-all is set on car_auctions so anon key won't work.
"""
from __future__ import annotations

import os
from datetime import date
from typing import Optional

from dateutil.relativedelta import relativedelta

from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

_client: Optional[Client] = None


def get_client() -> Client:
    global _client
    if _client is None:
        if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set"
            )
        _client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    return _client


def select_recent_matches(car_name: str, model_name: str, months: int) -> list[dict]:
    """Return 낙찰 rows matching car_name + model_name within the last `months` months.

    Excludes outlier rows (is_outlier=True) and returns all matching columns
    needed by matcher.py. Order is unspecified (matcher sorts by score).
    """
    cutoff = (date.today() - relativedelta(months=months)).isoformat()
    sb = get_client()
    resp = (
        sb.table("car_auctions")
        .select(
            "id,auction_date,car_name,model_name,full_title,year,grade,grade_first,"
            "color,mileage_km,options,final_price,status,is_outlier"
        )
        .eq("car_name", car_name)
        .eq("model_name", model_name)
        .eq("status", "낙찰")
        .or_("is_outlier.eq.false,is_outlier.is.null")
        .gte("auction_date", cutoff)
        .execute()
    )
    return resp.data or []


def count_all_auctions() -> int:
    """Return total row count in car_auctions (for /health endpoint)."""
    sb = get_client()
    resp = sb.table("car_auctions").select("id", count="exact").execute()
    return resp.count or 0


# ---------------------------------------------------------------------------
# Autocomplete index (distinct car_name + model_name pairs, cached in-process)
# ---------------------------------------------------------------------------

import time as _time

_INDEX_CACHE: dict = {"data": None, "ts": 0.0}
INDEX_CACHE_TTL_SEC = 600  # 10 minutes


def list_car_models_index(force_refresh: bool = False) -> list[dict]:
    """Return distinct (car_name, model_name) pairs from car_auctions.

    Reads from the `car_models_distinct` SQL view (one query) and caches the
    result in-process for INDEX_CACHE_TTL_SEC. Each entry is {car_name,
    model_name, n} where n is the row count for that combination.

    The view must be created by the operator once via Supabase SQL Editor:

        CREATE OR REPLACE VIEW public.car_models_distinct AS
        SELECT car_name, model_name, COUNT(*)::int AS n
        FROM public.car_auctions
        WHERE car_name IS NOT NULL AND car_name <> ''
          AND model_name IS NOT NULL AND model_name <> ''
        GROUP BY car_name, model_name
        ORDER BY car_name, model_name;
    """
    now = _time.time()
    if (not force_refresh) and _INDEX_CACHE["data"] is not None \
       and now - _INDEX_CACHE["ts"] < INDEX_CACHE_TTL_SEC:
        return _INDEX_CACHE["data"]
    sb = get_client()
    all_rows: list[dict] = []
    batch = 1000
    page = 0
    # Try the SQL view first (fast — pre-aggregated).
    try:
        while True:
            resp = (
                sb.table("car_models_distinct")
                .select("car_name, model_name, n")
                .range(page * batch, (page + 1) * batch - 1)
                .execute()
            )
            rows = resp.data or []
            all_rows.extend(rows)
            if len(rows) < batch:
                break
            page += 1
    except Exception:
        # Fallback: aggregate distinct from car_auctions directly. Slower
        # (~91 round-trips) but works even before the operator creates the
        # SQL view. Result is the same shape so callers don't care.
        all_rows = []
        seen: set[tuple[str, str]] = set()
        page = 0
        while True:
            resp = (
                sb.table("car_auctions")
                .select("car_name, model_name")
                .range(page * batch, (page + 1) * batch - 1)
                .execute()
            )
            rows = resp.data or []
            for r in rows:
                cn = (r.get("car_name") or "").strip()
                mn = (r.get("model_name") or "").strip()
                if cn and mn and (cn, mn) not in seen:
                    seen.add((cn, mn))
                    all_rows.append({"car_name": cn, "model_name": mn, "n": 0})
            if len(rows) < batch:
                break
            page += 1
        all_rows.sort(key=lambda r: (r["car_name"], r["model_name"]))
    _INDEX_CACHE["data"] = all_rows
    _INDEX_CACHE["ts"] = now
    return all_rows
