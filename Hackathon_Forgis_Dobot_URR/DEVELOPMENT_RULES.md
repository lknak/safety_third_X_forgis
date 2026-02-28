# Development Rules and Required Checks

This project currently has build/lint commands but no proper automated test suite configured.  
Use this document as the minimum quality gate before running development servers or shipping builds.

## 1) Standard Rules (Always)

1. Never start `dev` or `docker compose up --build` with uncommitted breaking changes.
2. Run checks locally first; do not use container build as your first feedback loop.
3. If any check fails, fix it before continuing.
4. Keep frontend and backend API contracts in sync (`/api/*`, `/ws` routes).
5. Do not merge code that was not validated with the checklists below.

## 2) Pre-Development Checklist (Before `dev`)

From `frontend/`:

```bash
npm ci
npm run lint
```

From `backend/`:

```bash
uv sync --frozen
uv run python -m compileall src
```

From repo root:

```bash
docker compose config
```

Pass criteria:

1. `npm run lint` has zero errors.
2. `compileall` completes without syntax/import-time failures.
3. `docker compose config` renders without schema/env errors.

## 3) Pre-Build Checklist (Before `build` / release image)

From `frontend/`:

```bash
npm ci
npm run lint
npm run build
```

From `backend/`:

```bash
uv sync --frozen
uv run python -m compileall src
```

From repo root:

```bash
docker compose build backend frontend
```

Pass criteria:

1. Frontend TypeScript + Vite build succeeds.
2. Backend source compiles cleanly.
3. Docker images build with no failing step.

## 4) Required Smoke Tests After Startup

After `docker compose up`:

```bash
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8000/api/flows
curl -fsS http://localhost:8000/api/health
```

If running frontend dev server:

```bash
curl -I http://localhost:3000
```

Pass criteria:

1. API health endpoints return `2xx`.
2. Frontend serves `200 OK`.
3. Browser console shows no repeated fetch/proxy failures for `/api` or `/ws`.

## 5) Why the Webpage Commonly “Keeps Failing to Load”

Most frequent causes in this repo:

1. Frontend cannot reach backend at `http://localhost:8000` (Vite proxy target).
2. Backend is up but hardware initialization is degraded, causing health/API failures.
3. Missing local tooling (`npm`, `uv`) means checks were skipped and breakages reached runtime.

## 6) Minimum Enforcement for Team Workflow

1. Before every PR: run all commands in section 3.
2. Before every local demo: run section 2 + section 4.
3. Reject PRs that skip these checks.

## 7) Next Upgrade (Recommended)

Add real automated tests and wire them into scripts:

1. Backend: `pytest` with FastAPI route tests (`/api/health`, `/api/flows`, `/ws`).
2. Frontend: `vitest` + React Testing Library for API hooks/components.
3. E2E: Playwright smoke flow (`home -> cell page -> health check visible`).
