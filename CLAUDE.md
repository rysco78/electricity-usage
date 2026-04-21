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

## Production deployment

Live at [energy.ryanrscott.com](https://energy.ryanrscott.com) on an AWS EC2 t3.micro (Ubuntu 22.04, Elastic IP). IAM instance profile grants DynamoDB + Bedrock access — no access keys in `.env` needed on EC2.

### Deploy files

| File | Purpose |
|---|---|
| `deploy/setup.sh` | One-shot setup for a fresh Ubuntu instance |
| `deploy/electricity-usage.service` | systemd unit — auto-starts on reboot, `--workers 2` |
| `deploy/nginx.conf` | nginx reverse proxy; `proxy_read_timeout 300s` for Bedrock; `client_max_body_size 20M` |

### Deploying updates

```bash
ssh ubuntu@<elastic-ip>
cd ~/electricity-usage
git pull
sudo systemctl restart electricity-usage
```

### Ubuntu setup gotcha

Install `libffi-dev` before pip packages or `cffi`/`cryptography` will fail to build:

```bash
sudo apt-get install -y libffi-dev
pip install --force-reinstall cffi cryptography python-jose[cryptography]
```

### Auth0 production config

Both `http://localhost:8000` and `https://energy.ryanrscott.com` must be in all three Auth0 app fields (Allowed Callback URLs, Allowed Logout URLs, Allowed Web Origins) so local dev and production work simultaneously.

## Responsive CSS breakpoints

All responsive styles are in `static/index.html`. Key breakpoints:

| Breakpoint | What it handles |
|---|---|
| `760px` | `.charts-duo` switches from side-by-side to stacked |
| `700px` | Step tracker labels hidden; restart-row buttons stack; chart/table horizontal scroll; stat card padding reduced |
| `600px` | Footer stacks |
| `540px` | Shell padding tightens; header wraps; auth button goes full-width below logo |

### Chart horizontal scroll pattern

Chart.js does not scroll natively. The working approach is:

```css
.chart-section { overflow-x: auto; -webkit-overflow-scrolling: touch; }
.chart-wrap    { min-width: 320px; }
```

The chart sizes to `min-width` and the section scrolls. Do **not** set `overflow` on `.chart-wrap` itself — that breaks Chart.js resize logic.

### Full-width stacked buttons

Buttons that need to stack full-width on mobile require both flex direction and explicit margin overrides for any inline `margin-left: auto` styles:

```css
.restart-row { flex-direction: column; align-items: stretch; gap: 10px; }
.restart-row .btn { justify-content: center; }
#restartBtn2, #saveBtn { margin-left: 0 !important; }
```
