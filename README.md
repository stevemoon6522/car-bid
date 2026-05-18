# car-bid — Used Car Auction Bid Price Recommendation

FastAPI web app that finds the most similar past auction results from a Supabase database and recommends a conservative bid price.

## Quickstart

### 1. Environment variables

Create a `.env` file (or set in Railway):

```
SUPABASE_URL=https://bpdafetvjyvvwbksvowu.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<your-service-role-key>
ADMIN_PASSWORD=<choose-a-password>
SESSION_HOURS=24
```

The app uses the **service-role key** because RLS deny-all is enabled on `car_auctions`.

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Ingest auction data (run once, then weekly for updates)

```bash
# Dry-run first — validates parsing without writing to DB:
python scripts/ingest_excel.py "path/to/car_auction.xlsx"

# Live upsert (incremental — safe to re-run; deduplicates by row_hash):
python scripts/ingest_excel.py "path/to/car_auction.xlsx" --upsert
```

The script reads sheet `이번주거래(누적)` (92K rows). Expect ~2-5 minutes for the full file.

### 4. Start dev server

```bash
uvicorn app:app --reload --port 8000
```

Open `http://localhost:8000/login` → enter ADMIN_PASSWORD → use the search form.

### 5. Run tests

```bash
python -m pytest tests/ -v
```

All tests are self-contained (no DB, no production Excel required).

### 6. Import smoke check

```bash
python -c "from app import app; print('OK')"
```

## Railway deploy

1. Create a new Railway project, connect to this GitHub repo.
2. Set env vars in Railway dashboard: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `ADMIN_PASSWORD`.
3. Push to `main` → Railway auto-deploys via `railway.json` config.
4. After first deploy, run ingest locally with `SUPABASE_*` env vars pointing at prod.

## Algorithm

- **Filter**: `car_name` + `model_name` exact match + `status='낙찰'` + last 3 months.
  Falls back to 6 months if no results. Returns "비교 불가" if still empty.
- **Score (0-100)**:
  - Grade (first letter A/B/C/D): 40 pts — exact=40, ±1=28, ±2=12, ±3=2
  - Year: 40 pts — same=40, 1y=32, 2y=24, 3y=16, 4y=8, 5y+=0
  - Mileage: 20 pts — ≤5%=20, ≤10%=16, ≤20%=12, ≤30%=8, ≤40%=4, else 0
- **Price adjustment** on each candidate's `final_price`:
  - Row has "선루프" in options AND input does not → -100만원
  - Row color is "흰색" AND input color is not → -100만원
  - Both rules apply cumulatively.
- **Recommended bid** = adjusted_price × 0.85 (conservative, -15%)

## DB schema

Table `public.car_auctions` in Supabase project `bpdafetvjyvvwbksvowu`.
Full schema in `sql/20260519_create_car_auctions.sql`.
