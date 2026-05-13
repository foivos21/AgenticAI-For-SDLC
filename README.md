# Agentic-AI-SDLC

Creating the Agentic Framework that can handle Jira issues and resolve coding problems.

## Docker Deployment (Conflict-Safe)

This repo now includes a Docker Compose stack configured to avoid common collisions with other Docker apps already running on your machine.

### Why it is safe by default

- Uses a dedicated Compose project name (`COMPOSE_PROJECT_NAME`) so containers/networks/volumes are isolated.
- Uses non-default host ports:
  - Backend: `18000`
  - Frontend: `15173`
- Binds services to loopback (`127.0.0.1`) by default (not exposed publicly).
- Uses an isolated named Docker volume for backend data (no host path bind conflict).

### First-time setup

1. Copy Docker environment file:
   - `cp .env.docker.example .env.docker`
2. If needed, change values in `.env.docker`:
   - `COMPOSE_PROJECT_NAME`
   - `BACKEND_HOST_PORT`
   - `FRONTEND_HOST_PORT`
   - bind addresses

### Run

Use helper script:

- Start/build:
  - `./scripts/docker_stack.sh up`
- See logs:
  - `./scripts/docker_stack.sh logs`
- List services:
  - `./scripts/docker_stack.sh ps`
- Stop:
  - `./scripts/docker_stack.sh down`

Or directly:

- `docker compose --env-file .env.docker up -d --build`
- `docker compose --env-file .env.docker down`

### URLs

- Frontend: `http://127.0.0.1:${FRONTEND_HOST_PORT}`
- Backend: `http://127.0.0.1:${BACKEND_HOST_PORT}`

## Thesis Notes

The thesis-oriented Jira SDLC architecture is documented here:

- [jira_sdlc_thesis_architecture.md](/Users/epameinondasdouros/Personal/Innovators_Hub/Freelancing/Thesis/Development/Agentic-AI-SDLC/docs/jira_sdlc_thesis_architecture.md)
