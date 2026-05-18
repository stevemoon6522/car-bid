"""matcher.py — Pure scoring and ranking functions for car auction bid recommendation.

No DB access here; all functions are deterministic and fully testable with fixtures.
"""
from __future__ import annotations

import statistics
from typing import Optional


# Grade ordinal map — only A/B/C/D are valid; anything else scores 0.
_GRADE_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3}

# Sunroof negation phrases — strip these before checking for "선루프".
_SUNROOF_NEGATIONS = ["비선루프", "선루프 없음", "선루프없음", "선루프 x", "선루프미장착"]

# White-color synonyms for price-adjustment check.
_WHITE_SYNONYMS = {"흰색", "백색", "화이트", "white"}


def score_grade(input_first: str, row_first: Optional[str]) -> int:
    """Return grade similarity score (0-40).

    Scoring by step distance between A/B/C/D:
      0 steps = 40, 1 step = 28, 2 steps = 12, 3 steps = 2
    Any non-ABCD value (or None) in either position returns 0.
    """
    if not input_first or not row_first:
        return 0
    a = _GRADE_ORDER.get(input_first.upper())
    b = _GRADE_ORDER.get(row_first.upper())
    if a is None or b is None:
        return 0
    diff = abs(a - b)
    return {0: 40, 1: 28, 2: 12, 3: 2}[diff]


def score_year(input_y: int, row_y: Optional[int]) -> int:
    """Return year similarity score (0-40).

    Scoring by absolute year difference:
      0y = 40, 1y = 32, 2y = 24, 3y = 16, 4y = 8, 5y+ = 0
    Returns 0 if row_y is None.
    """
    if row_y is None:
        return 0
    diff = abs(input_y - row_y)
    return {0: 40, 1: 32, 2: 24, 3: 16, 4: 8}.get(diff, 0)


def score_mileage(input_km: int, row_km: Optional[int]) -> int:
    """Return mileage similarity score (0-20).

    Scoring by |delta| / input_km:
      <=5%  = 20, <=10% = 16, <=20% = 12, <=30% = 8, <=40% = 4, else 0
    Returns 0 if row_km is None, input_km is 0, or input_km is negative.
    """
    if row_km is None or input_km is None or input_km <= 0:
        return 0
    ratio = abs(input_km - row_km) / input_km
    if ratio <= 0.05:
        return 20
    if ratio <= 0.10:
        return 16
    if ratio <= 0.20:
        return 12
    if ratio <= 0.30:
        return 8
    if ratio <= 0.40:
        return 4
    return 0


def apply_price_adjustments(row: dict, input_data: dict) -> tuple[int, list[str]]:
    """Apply option/color price adjustments to a candidate row's final_price.

    Rules (each subtracts 100만원, cumulative):
      1. Row options contain "선루프" AND input options do NOT contain "선루프" → -100
      2. Row color == "흰색" AND input color != "흰색" → -100

    Args:
        row: dict with keys 'final_price', 'options', 'color'
        input_data: dict with keys 'options' (str), 'color' (str)

    Returns:
        (adjusted_price, reasons) where reasons is a list of human-readable strings.
    """
    adjusted = row.get("final_price") or 0
    reasons: list[str] = []

    row_options = (row.get("options") or "").lower()
    input_options = (input_data.get("options") or "").lower()

    def _strip_negations(s: str) -> str:
        for neg in _SUNROOF_NEGATIONS:
            s = s.replace(neg, "")
        return s

    row_options_clean = _strip_negations(row_options)
    input_options_clean = _strip_negations(input_options)

    if "선루프" in row_options_clean and "선루프" not in input_options_clean:
        adjusted -= 100
        reasons.append("선루프 없음 -100만원")

    row_color = (row.get("color") or "").strip().lower()
    input_color = (input_data.get("color") or "").strip().lower()

    if row_color in _WHITE_SYNONYMS and input_color not in _WHITE_SYNONYMS:
        adjusted -= 100
        reasons.append("흰색 아님 -100만원")

    return adjusted, reasons


def rank_candidates(rows: list[dict], input_data: dict, top_n: int = 5) -> list[dict]:
    """Score, adjust, and rank candidate rows; return top_n enriched dicts.

    Each returned dict adds:
      score           — total 0-100
      score_breakdown — {'grade': int, 'year': int, 'mileage': int}
      adjusted_price  — final_price after option/color adjustments (만원)
      recommended_bid — adjusted_price * 0.85, rounded to int (만원)
      adjustment_reasons — list[str] of applied adjustments
    """
    input_grade = (input_data.get("grade_first") or "").strip().upper()
    input_year = input_data.get("year") or 0
    input_km = input_data.get("mileage_km") or 0

    scored = []
    for row in rows:
        g = score_grade(input_grade, row.get("grade_first"))
        y = score_year(input_year, row.get("year"))
        m = score_mileage(input_km, row.get("mileage_km"))
        total = g + y + m
        adjusted, reasons = apply_price_adjustments(row, input_data)
        recommended = round(adjusted * 0.85)
        enriched = {
            **row,
            "score": total,
            "score_breakdown": {"grade": g, "year": y, "mileage": m},
            "adjusted_price": adjusted,
            "recommended_bid": recommended,
            "adjustment_reasons": reasons,
        }
        scored.append(enriched)

    # Sort by score descending; ties broken by auction_date descending (more recent first).
    def _sort_key(x):
        ad = x.get("auction_date")
        if ad is None:
            return (-x["score"], 0)
        from datetime import date as _date_cls
        if isinstance(ad, _date_cls):
            return (-x["score"], -ad.toordinal())
        # String "YYYY-MM-DD" — convert to ordinal via date.fromisoformat.
        try:
            from datetime import date as _d
            return (-x["score"], -_d.fromisoformat(str(ad)).toordinal())
        except (ValueError, TypeError):
            return (-x["score"], 0)

    scored.sort(key=_sort_key)
    return scored[:top_n]


def summarize_bids(ranked: list[dict]) -> dict:
    """Return summary stats over the recommended_bid values of a ranked list."""
    if not ranked:
        return {}
    bids = [r["recommended_bid"] for r in ranked]
    return {
        "count": len(bids),
        "mean": round(statistics.mean(bids)),
        "median": round(statistics.median(bids)),
        "min": min(bids),
        "max": max(bids),
    }
