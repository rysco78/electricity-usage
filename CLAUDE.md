# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the app

```bash
# Install dependencies
pip install -r requirements.txt

# Start the dev server (auto-reloads on file changes)
uvicorn app:app --reload --port 8000
```

The app is served at `http://localhost:8000`. The FastAPI backend and the static frontend are served from the same process — FastAPI mounts `static/` at `/`.

## Environment variables

Create a `.env` file in the project root (auto-loaded by `python-dotenv` in `app.py`):

```
AUTH0_DOMAIN=dev-xxxx.us.auth0.com
AUTH0_CLIENT_ID=<SPA client ID>
DYNAMODB_TABLE=energy-plan-sessions
AWS_REGION=us-east-1
```

AWS credentials are read from `~/.aws/credentials` or the environment — no extra config needed if the AWS CLI is configured.

## Architecture

The entire app is a single FastAPI process with no build step:

- **`app.py`** — all backend logic: API routes, Auth0 JWT verification, DynamoDB session persistence, usage aggregation helper (`_aggregate_monthly`)
- **`static/index.html`** — the entire frontend: CSS, HTML, and ~900 lines of vanilla JS in one `<script>` tag. No framework, no bundler.
- **`parse_bill.py`** — extracts ESI ID and meter number from a PDF bill by sending raw text to Claude Sonnet via Bedrock
- **`parse_greenbutton.py`** — parses NAESB ESPI XML (Green Button format) into daily `{date, kwh, day_kwh, night_kwh}` rows and 24-element hourly averages. Day = 6am–9:59pm Central, night = 10pm–5:59am.
- **`power_to_choose.py`** — fetches plans from the Power to Choose API and ranks them by interpolating the three PUCT-published rate tiers (500/1000/2000 kWh) to the user's actual average usage
- **`smt_client.py`** — Smart Meter Texas consumer API client for on-demand meter reads (ODR). Historical data comes from Green Button XML, not this client.
- **`main.py`** — standalone CLI tool, not used by the web app

## Frontend state machine

The UI is a 4-step wizard. `goStep(n)` switches the active panel and updates the step tracker. State is held in module-level variables:

| Variable | Populated by |
|---|---|
| `billData` | `handleBill()` → `POST /api/extract` |
| `usageData` | `handleGreenButton()` → `POST /api/greenbutton` |
| `allPlans` | `fetchPlans()` → `POST /api/plans` |
| `lastRecommendation` | `renderRecommendation()` → `POST /api/recommend` |

`renderResults()` renders Step 3 (charts + stats table) from `usageData`. `renderPlans()` is the filtered/paginated plan table; filtering state lives in `activeType`, `activeTerm`, `activeCompanies`, `renewOnly`, `touOnly`, `currentPage`.

`showPlanModal(plan)` opens the plan detail modal with a live-recalculating day/night cost breakdown. The `recalc()` closure inside it destroys and recreates the Chart.js stacked bar on every rate input change.

## Auth and session persistence

- **Auth**: Auth0 SPA JS v1 (`@auth0/auth0-spa-js@1`). Login redirects to Auth0's hosted UI and back. The **ID token** (`getIdTokenClaims().__raw`) is sent as a Bearer token — not the access token, which is opaque without a registered API audience.
- **Backend verification**: `verify_token()` in `app.py` fetches Auth0 JWKS (cached 1 hour) and validates the ID token with `audience=AUTH0_CLIENT_ID`.
- **Persistence**: `PUT /api/session` saves `{bill_data, usage_data, zip_code, recommendation}` to DynamoDB. DynamoDB rejects Python `float` — use `_to_dynamo()` (JSON round-trip with `parse_float=Decimal`) before writing and `_from_dynamo()` after reading.

## Key external APIs

| API | Auth | Notes |
|---|---|---|
| Power to Choose | None | `http://api.powertochoose.org/api/PowerToChoose/plans` — requires `Referer` header |
| Smart Meter Texas | Username + password session | ODR only; 90s poll timeout |
| Anthropic Bedrock | AWS IAM | Model: `us.anthropic.claude-sonnet-4-6` |
| Auth0 JWKS | None | `https://{domain}/.well-known/jwks.json` |

## Checking JS syntax

The entire frontend JS lives in the single `<script>` block in `static/index.html`. To syntax-check it:

```bash
awk '/<script>/{p=1;next} /<\/script>/{p=0} p' static/index.html > /tmp/check.js && node --check /tmp/check.js
```
