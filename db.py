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
