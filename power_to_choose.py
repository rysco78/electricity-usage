"""
Power to Choose API client.
API: http://api.powertochoose.org/api/PowerToChoose
"""

import requests

PTC_API = "http://api.powertochoose.org/api/PowerToChoose"

_HEADERS = {
    "Accept": "application/json",
    "Referer": "https://www.powertochoose.org/",
    "Origin": "https://www.powertochoose.org",
}


def fetch_plans(zip_code: str) -> list[dict]:
    resp = requests.get(
        f"{PTC_API}/plans",
        params={
            "zip_code": zip_code.strip(),
            "renewable": 0,
            "rate_type": 0,
            "tdu_company_id": "",
            "page_size": 200,
            "page_number": 1,
        },
        headers=_HEADERS,
        timeout=30,
    )
    resp.raise_for_status()
    body = resp.json()
    return body.get("data", [])


def _interpolate_rate(p500: float, p1000: float, p2000: float, kwh: float) -> float | None:
    """Interpolate ¢/kWh for actual usage level from the three PUCT-reported tiers."""
    if not any([p500, p1000, p2000]):
        return None
    if kwh <= 500:
        return p500 or p1000 or p2000
    elif kwh <= 1000:
        if p500 and p1000:
            t = (kwh - 500) / 500
            return p500 + t * (p1000 - p500)
        return p1000 or p500
    elif kwh <= 2000:
        if p1000 and p2000:
            t = (kwh - 1000) / 1000
            return p1000 + t * (p2000 - p1000)
        return p2000 or p1000
    else:
        return p2000 or p1000


def rank_plans(plans: list[dict], avg_kwh: float, night_pct: float) -> list[dict]:
    results = []
    for p in plans:
        try:
            p500  = float(p.get("price_kwh500")  or 0)
            p1000 = float(p.get("price_kwh1000") or 0)
            p2000 = float(p.get("price_kwh2000") or 0)
        except (TypeError, ValueError):
            continue

        rate = _interpolate_rate(p500, p1000, p2000, avg_kwh)
        if not rate or rate <= 0:
            continue

        is_tou = bool(p.get("timeofuse"))
        renewable_pct = int(p.get("renewable_energy_id") or 0)

        results.append({
            "company":          (p.get("company_name") or "").strip(),
            "plan":             (p.get("plan_name")    or "").strip(),
            "rate_type":        (p.get("rate_type")    or "").strip(),
            "term_months":      int(p.get("term_value") or 0),
            "rate_cents_kwh":   round(rate, 2),
            "tier_500":         round(p500,  2),
            "tier_1000":        round(p1000, 2),
            "tier_2000":        round(p2000, 2),
            "estimated_monthly": round(rate * avg_kwh / 100, 2),
            "renewable_pct":    renewable_pct,
            "is_tou":           is_tou,
            "night_benefit":    is_tou and night_pct >= 0.35,
            "new_customer_only": bool(p.get("new_customer")),
            "prepaid":          bool(p.get("prepaid")),
            "pricing_details":  (p.get("pricing_details") or "").strip(),
            "fact_sheet":       p.get("fact_sheet") or "",
            "go_to_plan":       p.get("go_to_plan") or "",
        })

    results.sort(key=lambda x: x["estimated_monthly"])
    return results
