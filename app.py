from collections import defaultdict
from datetime import datetime, timezone
import json
import os
import re
import tempfile
import time

# Load .env file if present (local dev)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import anthropic
import boto3
from botocore.exceptions import ClientError
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles
from jose import jwt, JWTError
from pydantic import BaseModel
import requests as _requests

from parse_bill import extract_bill_data
from parse_greenbutton import parse_greenbutton
from power_to_choose import fetch_plans, rank_plans
from smt_client import SMTClient

app = FastAPI(title="TX Electricity Usage")

# ── Auth0 config (set via environment variables) ──────────────────
AUTH0_DOMAIN    = os.getenv("AUTH0_DOMAIN", "")       # e.g. dev-abc123.us.auth0.com
AUTH0_CLIENT_ID = os.getenv("AUTH0_CLIENT_ID", "")    # SPA client ID (frontend use)

# ── AWS / DynamoDB config ─────────────────────────────────────────
AWS_REGION      = os.getenv("AWS_REGION", "us-east-1")
DYNAMODB_TABLE  = os.getenv("DYNAMODB_TABLE", "energy-plan-sessions")

# ── JWKS cache (refresh every hour) ──────────────────────────────
_jwks_cache: dict = {}
_jwks_fetched_at: float = 0

def _get_jwks() -> dict:
    global _jwks_cache, _jwks_fetched_at
    if _jwks_cache and (time.time() - _jwks_fetched_at) < 3600:
        return _jwks_cache
    if not AUTH0_DOMAIN:
        raise HTTPException(status_code=503, detail="AUTH0_DOMAIN not configured on server.")
    resp = _requests.get(f"https://{AUTH0_DOMAIN}/.well-known/jwks.json", timeout=10)
    resp.raise_for_status()
    _jwks_cache = resp.json()
    _jwks_fetched_at = time.time()
    return _jwks_cache

_bearer = HTTPBearer(auto_error=False)

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(_bearer)) -> dict:
    if not credentials:
        raise HTTPException(status_code=401, detail="Authorization header required.")
    token = credentials.credentials
    try:
        jwks = _get_jwks()
        header = jwt.get_unverified_header(token)
        key = next(
            (k for k in jwks.get("keys", []) if k.get("kid") == header.get("kid")),
            None,
        )
        if not key:
            raise HTTPException(status_code=401, detail="Token signing key not found.")
        payload = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            issuer=f"https://{AUTH0_DOMAIN}/",
            audience=AUTH0_CLIENT_ID,
        )
        return payload
    except JWTError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")

def _dynamo_table():
    ddb = boto3.resource("dynamodb", region_name=AWS_REGION)
    return ddb.Table(DYNAMODB_TABLE)

def _to_dynamo(obj):
    """Recursively convert floats to Decimal for DynamoDB storage."""
    from decimal import Decimal
    return json.loads(json.dumps(obj), parse_float=Decimal)

def _from_dynamo(obj):
    """Recursively convert Decimals back to float for JSON responses."""
    from decimal import Decimal
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _from_dynamo(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_from_dynamo(v) for v in obj]
    return obj

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class OdrRequest(BaseModel):
    esi_id: str
    meter_number: str
    username: str
    password: str


class PlansRequest(BaseModel):
    zip_code: str
    avg_monthly_kwh: float
    night_pct: float


class RecommendRequest(BaseModel):
    usage: dict
    plans: list[dict]
    zip_code: str


class SessionPayload(BaseModel):
    bill_data: dict | None = None
    usage_data: dict | None = None
    zip_code: str | None = None
    recommendation: dict | None = None


def _aggregate_monthly(daily_rows: list[dict]) -> dict:
    monthly_kwh: dict[str, float] = defaultdict(float)
    monthly_day: dict[str, float] = defaultdict(float)
    monthly_night: dict[str, float] = defaultdict(float)
    monthly_days: dict[str, set] = defaultdict(set)
    all_days: set[str] = set()

    for row in daily_rows:
        try:
            dt = datetime.strptime(row["date"], "%m/%d/%Y")
            key = dt.strftime("%b %Y")
            monthly_kwh[key] += row["kwh"]
            monthly_day[key] += row.get("day_kwh", 0)
            monthly_night[key] += row.get("night_kwh", 0)
            monthly_days[key].add(row["date"])
            all_days.add(row["date"])
        except (ValueError, KeyError):
            continue

    sorted_monthly = []
    for k, v in sorted(monthly_kwh.items(), key=lambda x: datetime.strptime(x[0], "%b %Y")):
        days = len(monthly_days[k])
        sorted_monthly.append({
            "month": k,
            "kwh": round(v, 1),
            "day_kwh": round(monthly_day[k], 1),
            "night_kwh": round(monthly_night[k], 1),
            "days": days,
            "avg_daily_kwh": round(v / days, 1) if days else 0,
        })

    total = round(sum(r["kwh"] for r in sorted_monthly), 1)
    num_months = len(sorted_monthly)
    num_days = len(all_days)
    avg = round(total / num_months, 1) if num_months else 0
    avg_daily = round(total / num_days, 1) if num_days else 0

    return {
        "monthly": sorted_monthly,
        "total_kwh": total,
        "avg_kwh": avg,
        "avg_daily_kwh": avg_daily,
        "total_days": num_days,
    }


@app.post("/api/extract")
async def extract(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File must be a PDF.")
    contents = await file.read()
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(contents)
        tmp_path = tmp.name
    try:
        data = extract_bill_data(tmp_path)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    finally:
        os.unlink(tmp_path)
    return data


@app.post("/api/odr")
async def odr(req: OdrRequest):
    """Trigger an on-demand meter read and return the latest result."""
    client = SMTClient(req.username, req.password)
    try:
        client.authenticate()
    except Exception:
        raise HTTPException(status_code=401, detail="SMT authentication failed. Check your credentials.")

    try:
        client.request_odr(req.esi_id, req.meter_number)
        result = client.get_latest_odr(req.esi_id)
    except Exception as e:
        print(f"[ODR error] {type(e).__name__}: {e}")
        raise HTTPException(status_code=502, detail=str(e))

    if not result:
        raise HTTPException(status_code=504, detail="On-demand read timed out with no response. Try again in a few minutes.")

    print(f"[ODR result] {result!r}")

    if not isinstance(result, dict):
        raise HTTPException(status_code=502, detail=f"Unexpected SMT response: {result!r}")

    # Surface API-level errors clearly (result is already unwrapped from the data envelope)
    if result.get("errorCode"):
        raise HTTPException(status_code=502, detail=f"SMT error {result['errorCode']}: {result.get('errorMessage', result)}")

    return result


@app.post("/api/greenbutton")
async def greenbutton(file: UploadFile = File(...)):
    """Parse a Green Button XML file and return monthly usage totals."""
    contents = await file.read()
    suffix = ".xml" if (file.filename or "").lower().endswith(".xml") else ".zip"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(contents)
        tmp_path = tmp.name
    try:
        daily, hourly_avg = parse_greenbutton(tmp_path)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse Green Button file: {e}")
    finally:
        os.unlink(tmp_path)

    result = _aggregate_monthly(daily)
    result["hourly_avg"] = hourly_avg
    return result


@app.post("/api/plans")
async def plans(req: PlansRequest):
    """Fetch and rank Power to Choose plans for the given ZIP and usage profile."""
    zc = req.zip_code.strip()
    if not zc.isdigit() or len(zc) != 5:
        raise HTTPException(status_code=400, detail="Please enter a valid 5-digit Texas ZIP code.")
    try:
        raw = fetch_plans(zc)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not reach Power to Choose: {e}")
    if not raw:
        raise HTTPException(status_code=404, detail="No plans found for that ZIP code. Make sure it's a Texas ZIP code.")
    ranked = rank_plans(raw, req.avg_monthly_kwh, req.night_pct)
    return {
        "plans": ranked,
        "total_fetched": len(raw),
        "night_heavy": req.night_pct >= 0.35,
    }


@app.post("/api/recommend")
async def recommend(req: RecommendRequest):
    """Use Claude to recommend the best electricity plan for the user's usage profile."""
    monthly = req.usage.get("monthly", [])
    avg_kwh = req.usage.get("avg_kwh", 0)
    avg_daily = req.usage.get("avg_daily_kwh", 0)
    total_day = sum(m.get("day_kwh", 0) for m in monthly)
    total_night = sum(m.get("night_kwh", 0) for m in monthly)
    night_pct = total_night / (total_day + total_night) if (total_day + total_night) > 0 else 0
    peak = max(monthly, key=lambda x: x["kwh"]) if monthly else {}
    low  = min(monthly, key=lambda x: x["kwh"]) if monthly else {}

    monthly_lines = "\n".join(
        f"  {m['month']}: {m['kwh']} kWh  (day {m['day_kwh']} / night {m['night_kwh']})"
        for m in monthly
    )
    plans_lines = "\n".join(
        f"  {i+1:>2}. [{p['rate_type']:8}] {p['company']} — {p['plan']}"
        f" | {p['rate_cents_kwh']}¢/kWh | est ${p['estimated_monthly']:.0f}/mo"
        f" | {p['term_months']}mo term"
        + (" | TOU" if p["is_tou"] else "")
        + (f" | {p['renewable_pct']}% renewable" if p["renewable_pct"] else "")
        + (" | new customers only" if p["new_customer_only"] else "")
        + (f" | {p['pricing_details']}" if p["pricing_details"] else "")
        for i, p in enumerate(req.plans[:35])
    )

    prompt = f"""You are an electricity plan advisor. A Texas residential customer wants to minimize their electricity spend over the next 12 months.

USAGE PROFILE (ZIP {req.zip_code}):
- Average monthly usage: {avg_kwh:.1f} kWh
- Daily average: {avg_daily:.1f} kWh
- Night usage (10pm–6am): {total_night:.1f} kWh ({night_pct*100:.0f}% of total)
- Day usage (6am–10pm):   {total_day:.1f} kWh ({(1-night_pct)*100:.0f}% of total)
- Peak month: {peak.get('month','?')} at {peak.get('kwh','?')} kWh
- Lowest month: {low.get('month','?')} at {low.get('kwh','?')} kWh

MONTHLY BREAKDOWN:
{monthly_lines}

AVAILABLE PLANS (sorted by estimated monthly cost at {avg_kwh:.0f} kWh/month avg):
{plans_lines}

The estimated costs are interpolated from Power to Choose's published rates at 500/1000/2000 kWh tiers. For TOU plans, the reported rates assume an average usage pattern — a customer with {night_pct*100:.0f}% night usage may pay more or less than shown depending on the specific plan's night window and discount structure.

Recommend the single best plan to minimize total spend over 12 months. Return ONLY a raw JSON object (no markdown):
{{
  "recommended_company": "exact company name",
  "recommended_plan": "exact plan name",
  "estimated_annual_cost": 1234,
  "reasoning": "2-3 sentences explaining why this plan wins on cost",
  "key_factors": ["factor 1", "factor 2", "factor 3"],
  "runner_up": {{"company": "...", "plan": "...", "why": "one sentence"}},
  "watch_out": "one thing to verify before signing up"
}}"""

    try:
        client = anthropic.AnthropicBedrock()
        msg = client.messages.create(
            model="us.anthropic.claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )

        # Some models return thinking blocks before the text block — find the first text block.
        raw = next(
            (block.text for block in msg.content if hasattr(block, "text")),
            None,
        )
        if not raw:
            types = [type(b).__name__ for b in msg.content]
            raise ValueError(f"No text block in response (got: {types})")
        raw = raw.strip()
        print(f"[recommend raw] {raw[:300]!r}")

        # 1. Direct parse
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        # 2. Strip markdown code fences, then parse
        clean = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
        clean = re.sub(r"\s*```\s*$", "", clean, flags=re.MULTILINE).strip()
        try:
            return json.loads(clean)
        except json.JSONDecodeError:
            pass

        # 3. Extract first {...} block (handles prose before/after JSON)
        m = re.search(r"\{.*\}", clean, re.DOTALL)
        if not m:
            raise ValueError(f"No JSON object found in response: {raw[:300]!r}")
        return json.loads(m.group())

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI recommendation failed: {e}")


@app.get("/api/auth-config")
def auth_config():
    """Return Auth0 frontend config (safe to expose — these are public values)."""
    return {"domain": AUTH0_DOMAIN, "clientId": AUTH0_CLIENT_ID}


@app.get("/api/session")
def get_session(payload: dict = Depends(verify_token)):
    """Retrieve the saved session for the authenticated user."""
    user_id = payload.get("sub", "")
    try:
        table = _dynamo_table()
        resp = table.get_item(Key={"user_id": user_id})
        item = resp.get("Item")
        if not item:
            return {}
        item.pop("user_id", None)
        return _from_dynamo(item)
    except ClientError as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}")


@app.put("/api/session")
def put_session(body: SessionPayload, payload: dict = Depends(verify_token)):
    """Upsert the saved session for the authenticated user."""
    user_id = payload.get("sub", "")
    try:
        table = _dynamo_table()
        item: dict = {
            "user_id":    user_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if body.bill_data is not None:
            item["bill_data"] = body.bill_data
        if body.usage_data is not None:
            item["usage_data"] = body.usage_data
        if body.zip_code is not None:
            item["zip_code"] = body.zip_code
        if body.recommendation is not None:
            item["recommendation"] = body.recommendation
        table.put_item(Item=_to_dynamo(item))
        return {"ok": True}
    except ClientError as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}")


app.mount("/", StaticFiles(directory="static", html=True), name="static")
