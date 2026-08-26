# Outrospect

Personal research tool that collects publicly posted Social Media complaints directed at Indonesian government services, classifies them with an LLM, and surfaces trends in a dashboard.

---

## Prerequisites

- Python 3.11+
- Node.js 20+
- A PostgreSQL database (Supabase works)
- X/Twitter API v2 access (Bearer Token)
- An LLM API key (OpenAI or compatible)

---

## Backend

```bash
cd backend

# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy and fill in env vars
cp ../.env.example .env        # edit DATABASE_URL, TWITTER_BEARER_TOKEN, LLM_API_KEY, LLM_MODEL

# Run the development server
uvicorn app.main:app --reload --port 8000
```

Health check: `GET http://localhost:8000/health` should return `{"status": "ok"}`.

---

## Frontend

```bash
cd frontend

npm install
npm run dev
```

Opens at `http://localhost:3000`.

---

## Database

Migrations are plain SQL files in `/db`, numbered sequentially (`001_initial_schema.sql`, etc.).
Run each against your Postgres database manually:

```bash
psql $DATABASE_URL -f db/001_initial_schema.sql
```

---

## Environment Variables

See [`.env.example`](.env.example) for the full list.

| Variable | Description |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string |
| `TWITTER_BEARER_TOKEN` | X/Twitter API v2 Bearer Token |
| `LLM_API_KEY` | API key for the LLM provider |
| `LLM_MODEL` | Model identifier (e.g. `gpt-4o-mini`) |

---

## Project Structure

```
outrospect/
├── backend/
│   ├── app/
│   │   ├── api/          # FastAPI route modules
│   │   ├── jobs/         # APScheduler job definitions
│   │   ├── models/       # SQLAlchemy models
│   │   ├── services/     # ingestion, classification, aggregation logic
│   │   ├── config.py     # pydantic-settings config
│   │   └── main.py       # application entry point
│   └── requirements.txt
├── db/                   # SQL migration files
├── frontend/             # Next.js App Router app
└── .env.example
```
