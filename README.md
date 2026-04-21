# Energy Plan Optimizer

A Texas electricity plan optimizer that analyzes your usage history and recommends the best available plan for your home. Upload your bill and Green Button data, explore your consumption patterns, and let Claude AI pick the plan that will save you the most money.

---

## Features

- **Bill parsing** — drop a PDF electricity bill; ESI ID and meter number are extracted automatically via Claude AI
- **Usage analysis** — upload a Green Button XML export from Smart Meter Texas for a full monthly breakdown with day/night split, hourly heatmap, and usage charts
- **Plan comparison** — fetches live plans from the [Power to Choose](https://powertochoose.org) registry, ranked by estimated monthly cost at your actual usage level
- **AI recommendation** — Claude Sonnet analyzes your usage profile against the top plans and recommends the single best option with reasoning
- **Session save/restore** — sign in with Auth0 to save your data and resume without re-uploading

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python · FastAPI · Uvicorn |
| Frontend | Vanilla JS · Chart.js · Plus Jakarta Sans |
| Auth | Auth0 SPA JS v1 |
| Database | AWS DynamoDB |
| AI | Anthropic Claude Sonnet via AWS Bedrock |

---

## Prerequisites

- Python 3.11+
- AWS CLI configured (`~/.aws/credentials` or IAM role)
- An [Auth0](https://auth0.com) account
- An [AWS](https://aws.amazon.com) account with DynamoDB access

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Create an Auth0 application

1. In the Auth0 dashboard, create a new **Single Page Web Application**
2. Under Settings, add `http://localhost:8000` to:
   - Allowed Callback URLs
   - Allowed Logout URLs
   - Allowed Web Origins
3. Note the **Domain** and **Client ID**

### 3. Create a DynamoDB table

```bash
aws dynamodb create-table \
  --table-name energy-plan-sessions \
  --attribute-definitions AttributeName=user_id,AttributeType=S \
  --key-schema AttributeName=user_id,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --region us-east-1
```

### 4. Configure environment variables

Create a `.env` file in the project root:

```env
AUTH0_DOMAIN=dev-xxxx.us.auth0.com
AUTH0_CLIENT_ID=your_client_id_here
DYNAMODB_TABLE=energy-plan-sessions
AWS_REGION=us-east-1
```

### 5. Start the server

```bash
uvicorn app:app --reload --port 8000
```

Open `http://localhost:8000`.

---

## Usage

The app walks through four steps:

1. **Upload Bill** — drag and drop your PDF electricity bill to extract your ESI ID and meter number
2. **Upload Usage Data** — download a Green Button XML from [Smart Meter Texas](https://smartmetertexas.com) (My Account → Green Button → Download My Data), then upload it here
3. **Your Report** — review monthly usage charts, day/night breakdown, and hourly consumption patterns
4. **Best Plans** — enter your ZIP code, browse ranked plans, click any plan for a detailed monthly cost breakdown, and request an AI recommendation

---

## API endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/extract` | Extract ESI ID and meter number from a PDF bill |
| `POST` | `/api/greenbutton` | Parse a Green Button XML file into monthly usage data |
| `POST` | `/api/odr` | Trigger an on-demand meter read via Smart Meter Texas |
| `POST` | `/api/plans` | Fetch and rank Power to Choose plans for a ZIP code |
| `POST` | `/api/recommend` | Generate an AI plan recommendation |
| `GET` | `/api/auth-config` | Return Auth0 domain and client ID for the frontend |
| `GET` | `/api/session` | Load a saved session (requires Auth0 bearer token) |
| `PUT` | `/api/session` | Save a session (requires Auth0 bearer token) |

---

## Getting your Green Button data

1. Log in to [smartmetertexas.com](https://www.smartmetertexas.com)
2. Go to **My Account → Green Button → Download My Data**
3. Select a date range (up to 24 months available) and choose **XML** format
4. Upload the downloaded file in Step 2 of the app
