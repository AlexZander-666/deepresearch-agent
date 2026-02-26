# Repository Guidelines

## Project Structure & Module Organization
- `api.py` boots FastAPI and wires routers from domain packages such as `agent/`, `auth/`, `credentials/`, `templates/`, `triggers/`, and `knowledge_base/`.
- Keep HTTP handlers in `<module>/api.py`; keep business logic in `*_service.py`; keep shared infrastructure clients in `services/` and shared helpers in `utils/`.
- Background execution lives in `run_agent_background.py`; sandbox integrations are in `sandbox/`; SQL changes live in `supabase/migrations/` and `migrations/`.
- Integration test scripts are in `tests/`. Environment setup references are `.env.example` and `ENV_CONFIG.md`.

## Build, Test, and Development Commands
- `python -m venv .venv && .\.venv\Scripts\activate && pip install -r requirements.txt`: create a local environment and install dependencies.
- `python api.py`: run the API locally on `0.0.0.0:8000` with reload enabled.
- `docker compose up --build`: run `api`, `worker`, and `redis` in a production-like local stack.
- `uv run dramatiq --skip-logging --processes 4 --threads 4 run_agent_background`: run the background worker directly.
- `python tests/02_test_simple_sandbox.py` (or other `tests/*.py`): run integration scripts.

## Coding Style & Naming Conventions
- Python uses 4-space indentation, `snake_case` for functions/files/variables, and `PascalCase` for classes.
- Prefer async functions for I/O-heavy paths and keep route files thin by moving external API/DB logic into service modules.
- Use structured logging through `utils.logger`; avoid `print` in application code.

## Testing Guidelines
- Current coverage is script-based integration testing rather than a centralized `pytest` suite.
- Name new scripts `NN_test_<feature>.py` in `tests/` to match existing naming.
- For each feature, include at least one happy-path and one failure-path check.
- Before merging, verify API and worker health (for example, `/api/health` and `python worker_health.py`).

## Commit & Pull Request Guidelines
- This workspace snapshot does not include `.git` history, so local commit conventions cannot be verified from logs.
- Use Conventional Commit style: `feat:`, `fix:`, `chore:` (example: `fix(auth): handle expired refresh token`).
- PRs should include problem statement, summary of changes, config/migration impact, linked issues, and test evidence (commands plus results).

## Security & Configuration Tips
- Never commit live credentials. Keep secrets in `.env` and treat `.env.example` as placeholders only.
- Rotate external provider keys (LLM, E2B/PPIO, Tavily, Firecrawl) and document any new variables in `ENV_CONFIG.md`.
