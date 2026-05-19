"""app.py — FastAPI web app for used-car auction bid-price recommendation.

Routes:
  GET  /login   — login page
  POST /login   — authenticate; set session cookie + csrf cookie
  POST /logout  — CSRF-protected; clear session; redirect to /login
  GET  /        — search form (requires auth)
  POST /search  — CSRF-protected; run matcher; render results (requires auth)
  GET  /health  — liveness + DB row count (public)
"""
from __future__ import annotations

import os
import re
import secrets
import time
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, Form, Cookie, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import db
import matcher as m

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
SESSION_HOURS = int(os.environ.get("SESSION_HOURS", "24"))
LOGIN_LOCKOUT_WINDOW_SEC = 60
LOGIN_MAX_FAILURES = 5

# ---------------------------------------------------------------------------
# Session store (in-memory; single-instance Railway deployment)
# ---------------------------------------------------------------------------

_sessions: dict[str, datetime] = {}
# Maps IP → list of failure timestamps
_login_failures: dict[str, list[float]] = {}


def _now() -> datetime:
    return datetime.utcnow()


def _make_session() -> str:
    sid = secrets.token_urlsafe(32)
    _sessions[sid] = _now() + timedelta(hours=SESSION_HOURS)
    return sid


def _sweep_sessions() -> None:
    now = _now()
    expired = [sid for sid, exp in _sessions.items() if exp < now]
    for sid in expired:
        _sessions.pop(sid, None)


def _is_logged_in(session_id: Optional[str]) -> bool:
    if len(_sessions) > 50:
        _sweep_sessions()
    if not session_id or session_id not in _sessions:
        return False
    if _sessions[session_id] < _now():
        _sessions.pop(session_id, None)
        return False
    return True


def _admin_or_redirect(session_id: Optional[str]) -> Optional[RedirectResponse]:
    if not _is_logged_in(session_id):
        return RedirectResponse("/login", status_code=302)
    return None


# ---------------------------------------------------------------------------
# Login failure rate-limiting with TTL sweep
# ---------------------------------------------------------------------------

def _sweep_login_failures() -> None:
    """Purge entries older than LOGIN_LOCKOUT_WINDOW_SEC; cap dict at 1000 entries."""
    cutoff = time.time() - LOGIN_LOCKOUT_WINDOW_SEC
    for ip in list(_login_failures.keys()):
        _login_failures[ip] = [t for t in _login_failures[ip] if t > cutoff]
        if not _login_failures[ip]:
            del _login_failures[ip]
    # Cap size: if still > 1000 entries, drop oldest 500 by their most-recent timestamp.
    if len(_login_failures) > 1000:
        sorted_ips = sorted(_login_failures, key=lambda ip: max(_login_failures[ip]))
        for ip in sorted_ips[:500]:
            del _login_failures[ip]


def _check_login_rate_limit(client_ip: str) -> bool:
    """Return True if this IP is currently rate-limited (too many recent failures)."""
    _sweep_login_failures()
    cutoff = time.time() - LOGIN_LOCKOUT_WINDOW_SEC
    recent = [t for t in _login_failures.get(client_ip, []) if t > cutoff]
    return len(recent) >= LOGIN_MAX_FAILURES


def _record_login_failure(client_ip: str) -> None:
    _login_failures.setdefault(client_ip, []).append(time.time())


# ---------------------------------------------------------------------------
# CSRF helpers (double-submit cookie pattern)
# ---------------------------------------------------------------------------

def _new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def _require_csrf(request: Request, form_token: Optional[str]) -> None:
    """Raise 403 if CSRF cookie and form field don't match."""
    cookie_token = request.cookies.get("csrf_token")
    if not cookie_token or not form_token:
        raise HTTPException(status_code=403, detail="CSRF token missing")
    if not secrets.compare_digest(cookie_token, form_token):
        raise HTTPException(status_code=403, detail="CSRF token mismatch")


# ---------------------------------------------------------------------------
# Input parsing helpers
# ---------------------------------------------------------------------------

_MAN_RE = re.compile(r"^([0-9,]+)\s*만$", re.IGNORECASE)


def _parse_korean_int(s: str, field_name: str = "값") -> int:
    """Parse a Korean-style integer string.

    Handles:
      - Plain integers: "80000"
      - Comma-separated: "80,000"
      - 만 suffix: "8만" → 80000

    Raises HTTPException 400 with a Korean error message on invalid input.
    """
    cleaned = s.strip().replace(",", "")
    man_m = _MAN_RE.match(s.strip())
    if man_m:
        cleaned = man_m.group(1).replace(",", "")
        try:
            return int(cleaned) * 10000
        except ValueError:
            pass
    try:
        return int(cleaned)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} 형식이 올바르지 않습니다. 숫자만 입력하세요 (예: 80000 또는 8만).",
        )


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="car-bid", version="0.1.0")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login")
async def login_submit(request: Request, password: str = Form(...)):
    if not ADMIN_PASSWORD:
        return templates.TemplateResponse(
            request, "login.html",
            {"error": "서버 비밀번호가 설정되지 않았습니다."},
        )
    client_ip = request.client.host if request.client else "unknown"
    if _check_login_rate_limit(client_ip):
        return templates.TemplateResponse(
            request, "login.html",
            {"error": "로그인 시도 횟수 초과. 잠시 후 다시 시도하세요."},
            status_code=429,
        )
    if not secrets.compare_digest(password, ADMIN_PASSWORD):
        _record_login_failure(client_ip)
        return templates.TemplateResponse(
            request, "login.html", {"error": "비밀번호가 틀렸습니다."}
        )
    # Success — clear failure history, create session + CSRF token.
    _login_failures.pop(client_ip, None)
    sid = _make_session()
    csrf = _new_csrf_token()
    resp = RedirectResponse("/", status_code=302)
    resp.set_cookie(
        "session_id", sid, max_age=SESSION_HOURS * 3600, httponly=True, samesite="lax"
    )
    # csrf_token must be readable by JS/form (httponly=False) for double-submit pattern.
    resp.set_cookie("csrf_token", csrf, max_age=SESSION_HOURS * 3600, httponly=False, samesite="lax")
    return resp


@app.post("/logout")
async def logout(
    request: Request,
    csrf_token: str = Form(""),
    session_id: Optional[str] = Cookie(None),
):
    _require_csrf(request, csrf_token)
    if session_id:
        _sessions.pop(session_id, None)
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie("session_id")
    resp.delete_cookie("csrf_token")
    return resp


# ---------------------------------------------------------------------------
# Main routes
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, session_id: Optional[str] = Cookie(None)):
    if r := _admin_or_redirect(session_id):
        return r
    csrf = request.cookies.get("csrf_token", "")
    return templates.TemplateResponse(request, "index.html", {"csrf_token": csrf})


@app.post("/search", response_class=HTMLResponse)
async def search(
    request: Request,
    car_name: str = Form(...),
    model_name: str = Form(...),
    year_raw: str = Form(..., alias="year"),
    mileage_km_raw: str = Form(..., alias="mileage_km"),
    grade_first: str = Form(...),
    color: str = Form(...),
    options: str = Form(""),
    csrf_token: str = Form(""),
    session_id: Optional[str] = Cookie(None),
):
    if r := _admin_or_redirect(session_id):
        return r
    _require_csrf(request, csrf_token)

    year = _parse_korean_int(year_raw, "년식")
    mileage_km = _parse_korean_int(mileage_km_raw, "주행거리")

    input_data = {
        "car_name": car_name.strip(),
        "model_name": model_name.strip(),
        "year": year,
        "mileage_km": mileage_km,
        "grade_first": grade_first.strip().upper(),
        "color": color.strip(),
        "options": options.strip(),
    }

    # Try 3-month window first, fall back to 6 months.
    rows = db.select_recent_matches(car_name.strip(), model_name.strip(), months=3)
    period_months = 3

    if not rows:
        rows = db.select_recent_matches(car_name.strip(), model_name.strip(), months=6)
        period_months = 6

    csrf = request.cookies.get("csrf_token", "")

    if not rows:
        return templates.TemplateResponse(
            request, "results.html",
            {
                "no_match": True,
                "input_data": input_data,
                "period_months": period_months,
                "csrf_token": csrf,
            },
        )

    ranked = m.rank_candidates(rows, input_data, top_n=5)
    summary = m.summarize_bids(ranked)

    return templates.TemplateResponse(
        request, "results.html",
        {
            "no_match": False,
            "input_data": input_data,
            "ranked": ranked,
            "summary": summary,
            "period_months": period_months,
            "total_candidates": len(rows),
            "csrf_token": csrf,
        },
    )


@app.get("/health")
async def health():
    try:
        rows = db.count_all_auctions()
        return JSONResponse({"ok": True, "service": "car", "db": True, "rows": rows})
    except Exception as e:
        return JSONResponse(
            {"ok": False, "service": "car", "db": False, "error": str(e)},
            status_code=503,
        )
