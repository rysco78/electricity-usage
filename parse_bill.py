import json
import re

import anthropic
import pdfplumber


def extract_bill_data(pdf_path: str) -> dict:
    """Extract ESI ID and meter number from any Texas electricity bill using Claude."""
    with pdfplumber.open(pdf_path) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)

    if not text.strip():
        raise ValueError("Could not extract text from this PDF. The file may be scanned or image-based.")

    client = anthropic.AnthropicBedrock()
    msg = client.messages.create(
        model="us.anthropic.claude-sonnet-4-6",
        max_tokens=512,
        messages=[{
            "role": "user",
            "content": f"""Extract billing details from this Texas electricity bill text.

Fields to extract:
- esi_id: 17-digit number, often labeled "ESI ID", "ESI:", or "ESIID"
- meter_number: shorter alphanumeric identifier, labeled "Meter Number", "Meter #", or "Meter No". Strip trailing letters (e.g. "163106093LG" → "163106093")
- provider: the electricity retailer/provider name (e.g. "Reliant Energy", "TXU Energy", "Green Mountain Energy")
- plan_name: the rate plan or product name shown on the bill (e.g. "Simple Rate 12", "Stellar Home 24")
- rate_cents_kwh: the energy charge rate in cents per kWh as a number (look for lines like "Energy Charge", "Electric Energy", or "kWh Charge" — use ONLY the per-kWh energy rate, not TDU/delivery charges, not a blended bill average)

Return ONLY a raw JSON object, no markdown:
{{"esi_id": "17-digit number or null", "meter_number": "numeric string or null", "provider": "string or null", "plan_name": "string or null", "rate_cents_kwh": number or null}}

Bill text:
{text[:6000]}"""
        }],
    )

    raw = msg.content[0].text.strip()
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if not m:
            raise ValueError("Could not parse AI response when reading bill.")
        result = json.loads(m.group())

    if not result.get("esi_id"):
        raise ValueError("Could not find an ESI ID in this bill. Please make sure it's a Texas electricity bill.")

    return {
        "esi_id":          result.get("esi_id"),
        "meter_number":    result.get("meter_number"),
        "provider":        result.get("provider"),
        "plan_name":       result.get("plan_name"),
        "rate_cents_kwh":  result.get("rate_cents_kwh"),
    }
