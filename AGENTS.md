# Repository Guidelines

## Project Structure & Module Organization
- `frontend/`: Next.js 15 + TypeScript app. Main code lives in `frontend/src/`, static files in `frontend/public/`, and app/tooling config in files like `next.config.ts`, `eslint.config.mjs`, and `tsconfig.json`.
- `backend/`: FastAPI service. Entry point is `backend/api.py`; domain modules are split by folder (`backend/agent/`, `backend/auth/`, `backend/services/`, etc.); operational scripts are in `backend/scripts/`; sandbox utilities are in `backend/sandbox/`; integration-style checks are in `backend/tests/`.

## Build, Test, and Development Commands
- Frontend setup/run:
  - `cd frontend && npm install`
  - `npm run dev` (local dev server at `http://localhost:3000`)
  - `npm run build` (production build), `npm run start` (serve build)
  - `npm run lint`, `npm run format`, `npm run format:check`
- Backend setup/run:
  - `cd backend && pip install -r requirements.txt`
  - `python api.py` (starts Uvicorn on `0.0.0.0:8000` with reload)
  - Optional container flow: `docker compose up --build`
- Backend integration checks:
  - Example: `cd backend && python tests/02_test_simple_sandbox.py`

## Coding Style & Naming Conventions
- Frontend formatting is enforced via Prettier (`tabWidth: 2`, single quotes, semicolons, trailing commas).
- Use `@/*` path aliases in frontend imports (configured in `frontend/tsconfig.json`).
- Keep React component exports in PascalCase; keep file/folder names consistent with existing patterns (mostly kebab-case file names in `src/components/`).
- Python code should follow PEP 8 basics: 4-space indentation, snake_case for modules/functions, and domain-grouped API/router modules.

## Testing Guidelines
- Current backend tests in `backend/tests/` are integration-oriented scripts (`NN_test_*.py`) and may require external services (Redis, Ollama, E2B/PPIO sandboxes, API keys).
- Run targeted scripts directly with Python from `backend/`.
- `uv.lock` includes `pytest`, but no repository-wide coverage threshold is currently enforced.

## Commit & Pull Request Guidelines
- This workspace does not include `.git` history, so follow Conventional Commits by default, e.g. `feat(frontend): add workflow filter`, `fix(backend): handle auth refresh race`.
- PRs should include: concise summary, changed paths, environment/config updates, verification commands with results, and screenshots for UI changes.

## Security & Configuration Tips
- Use template env files (`backend/.env.example`, `frontend/env.example`) and keep real secrets in untracked local env files.
- Never commit API keys, sandbox credentials, or production connection strings.
