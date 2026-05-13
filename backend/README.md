# TechMellon Airline Backend

## Local Run

Prerequisite: copy `.env.example` to `.env`, set Jira/OpenAI credentials, and choose either the default local SQLite database or your own Postgres `DATABASE_URL`.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
alembic upgrade head
python -m app.scripts.seed_flights
python -m app.scripts.seed_bookings
python -m app.scripts.seed_knowledge
uvicorn app.main:app --reload
```

The backend exposes Jira planning and ALMAS orchestration endpoints:

- `POST /api/jira/issues/sync` syncs Jira issues into local linkage storage
- `GET /api/jira/issues` lists synced issues
- `POST /api/jira/issues/{issue_key}/plan` generates a developer-stage implementation package shortcut
- `POST /api/almas/issues/{issue_key}/runs` starts a full ALMAS run
- `GET /api/almas/runs` lists ALMAS runs
- `GET /api/almas/runs/{run_id}` returns run artifacts and status
- `POST /api/almas/runs/{run_id}/approve` records approval and generates the GitHub handoff package
- `POST /api/almas/runs/{run_id}/retry` retries a blocked or review-rejected run
- `GET /api/almas/issues/{issue_key}/latest-run` fetches the latest run for one Jira issue

Required Jira/OpenAI environment variables:

```text
JIRA_BASE_URL=
JIRA_USER_EMAIL=
JIRA_API_TOKEN=
JIRA_PROJECT_KEY=
OPENAI_API_KEY=
ALMAS_ANALYZER_MODEL=openai:gpt-4o-mini
ALMAS_PLANNER_MODEL=openai:gpt-4o-mini
ALMAS_FIXER_MODEL=openai:gpt-4o-mini
ALMAS_MAX_REVIEW_REVISIONS=1
ALMAS_DATA_DIR=
GITHUB_TOKEN=
GITHUB_REPO=
GITHUB_BASE_BRANCH=main
```

## Railway Deployment

This backend can be deployed to Railway as a public FastAPI service.

### Required setup

1. Create a Railway project and deploy the `backend` directory from GitHub or with the Railway CLI.
2. Attach a Railway Volume to the service.
3. Mount the volume at `/app/data`.
4. Generate a public domain for the service.

### Runtime behavior

The deployment start command is defined in [railway.json](/Users/epameinondasdouros/Personal/Innovators_Hub/Freelancing/Thesis/Development/Agentic-AI-SDLC/backend/railway.json) and runs [start.sh](/Users/epameinondasdouros/Personal/Innovators_Hub/Freelancing/Thesis/Development/Agentic-AI-SDLC/backend/start.sh), which:

- points SQLite at the mounted Railway volume when available
- runs Alembic migrations
- seeds flights, bookings, and knowledge data idempotently
- starts the FastAPI app on Railway's assigned `PORT`

### Suggested Railway environment variables

Set these in Railway if needed:

```text
APP_ENV=production
APP_NAME=TechMellon Airline Backend
API_PREFIX=/api
ENABLE_ELEVENLABS_AGENTIC=false
```

`DATABASE_URL` is optional on Railway if the volume is mounted, because [start.sh](/Users/epameinondasdouros/Personal/Innovators_Hub/Freelancing/Thesis/Development/Agentic-AI-SDLC/backend/start.sh) defaults it to:

```text
sqlite:///${RAILWAY_VOLUME_MOUNT_PATH}/techmellon_airline.db
```

Important:

- If you previously set `DATABASE_URL=sqlite:///./techmellon_airline.db` in Railway, remove it. That points SQLite at the container filesystem, not the mounted volume.
- If the volume is mounted at `/app/data`, the persistent SQLite path should be:

```text
sqlite:////app/data/techmellon_airline.db
```

- The startup script now logs the effective `DATABASE_URL`, `RAILWAY_VOLUME_MOUNT_PATH`, and bootstrap marker path so you can verify persistence in Railway logs.

### Verification

After deploy, verify:

- `/health`
- `/docs`
- `/api/admin/flights`
- `/api/admin/bookings`
- `/api/knowledge/topics`
