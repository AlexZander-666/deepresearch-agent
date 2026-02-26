# Repository Guidelines

## Project Structure & Module Organization
- `src/app`: Next.js App Router pages, route groups (`(home)`, `(dashboard)`), and API routes.
- `src/components`: Feature and shared UI code. Base primitives live in `src/components/ui`; larger domains include `agents/`, `thread/`, `workflows/`, and `home/`.
- `src/hooks`: Reusable hooks, with server-state hooks grouped under `src/hooks/react-query`.
- `src/lib`: Core utilities, API clients, auth helpers, and shared business logic.
- `public`: Static assets (images, icons, media).
- Keep tests colocated with source using `*.test.ts`/`*.test.tsx` (example: `src/components/workflows/utils/workflow-structure-utils.test.ts`).

## Build, Test, and Development Commands
- `npm run dev`: Start the local Next.js dev server (Turbopack).
- `npm run build`: Build the production bundle.
- `npm run start`: Run the production server from the build output.
- `npm run lint`: Run ESLint (`next/core-web-vitals` + TypeScript rules).
- `npm run format`: Apply Prettier formatting across the repo.
- `npm run format:check`: Verify formatting without changing files.
- No `test` script is currently defined in `package.json`; add one when introducing a test runner.

## Coding Style & Naming Conventions
- Language stack: TypeScript + React (Next.js 15).
- Import paths: use alias `@/*` for `src/*` imports.
- Prettier baseline (`.prettierrc`): 2-space indentation, semicolons, single quotes, trailing commas, `printWidth: 80`.
- Naming patterns:
  - Components: `.tsx` files in kebab-case, React component names in PascalCase.
  - Hooks: `use-*.ts` or `use-*.tsx`.
  - Utilities/types: descriptive kebab-case filenames.
- Run `npm run lint && npm run format:check` before submitting changes.

## Testing Guidelines
- Prefer colocated unit tests named `*.test.ts` or `*.test.tsx`.
- Prioritize tests for parsing, hooks, API helpers, and non-trivial state transitions.
- For UI-heavy changes, include manual verification steps in the PR until broader automated coverage is added.

## Commit & Pull Request Guidelines
- This workspace snapshot does not include local `.git` history; use Conventional Commit style: `feat:`, `fix:`, `refactor:`, `docs:`, `chore:`.
- Keep commits focused and atomic (one concern per commit).
- PR checklist:
  - Clear summary and why the change is needed.
  - Linked issue/task ID.
  - Screenshots or short recordings for UI changes.
  - Any env/config updates reflected in `env.example`.

## Security & Configuration Tips
- Never commit secrets; keep sensitive values in local `.env`.
- Treat `env.example` as the source of truth for required variables.
- Ensure frontend/backend URL settings are consistent before testing integrations.
