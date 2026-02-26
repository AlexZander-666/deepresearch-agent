# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

FuFanManus (Kortix Frontend) is a Next.js 15-based AI agent platform frontend that enables users to interact with intelligent agents for task automation, data analysis, and research. The application uses a custom authentication system (no Supabase), React Query for state management, and communicates with a Python FastAPI backend.

## Development Commands

```bash
# Development
npm run dev          # Start dev server with Turbopack (http://localhost:3000)

# Build & Production
npm run build        # Build for production
npm run start        # Start production server

# Code Quality
npm run lint         # Run ESLint
npm run format       # Format code with Prettier
npm run format:check # Check formatting without changes
```

## Environment Configuration

Required environment variables in `.env.local`:

```sh
# Backend API (includes /api prefix)
NEXT_PUBLIC_BACKEND_URL=http://localhost:8000/api

# Frontend URL (for callbacks)
NEXT_PUBLIC_URL=http://localhost:3000

# Environment mode: LOCAL | STAGING | PRODUCTION
NEXT_PUBLIC_ENV_MODE=LOCAL

# Optional
NEXT_PUBLIC_TOLT_REFERRAL_ID=
```

## Architecture

### App Router Structure

The app uses Next.js 15 App Router with route groups:

- **`(dashboard)/`** - Main authenticated dashboard routes
  - **`(personalAccount)/settings/`** - Personal account settings (billing, env vars, usage)
  - **`(teamAccount)/[accountSlug]/settings/`** - Team account settings (members, billing)
  - **`agents/`** - Agent management and configuration
    - `config/[agentId]/workflow/[workflowId]/` - Workflow builder
    - `[threadId]/` - Agent conversation threads
  - **`projects/[projectId]/thread/`** - Project-specific chat threads
- **`(home)/`** - Public landing pages
- **`auth/`** - Authentication pages (login, register)
- **`api/`** - API routes (db access, edge-flags, integrations, webhooks)

### Core Libraries & Patterns

#### State Management

- **React Query (@tanstack/react-query)** - Server state, API calls, caching
  - Query hooks in `src/hooks/react-query/`
  - Configuration in `src/app/providers.tsx`
- **Zustand** - Client state (modals, agent selection, auth tracking)
  - Stores in `src/lib/stores/`
  - Modal state: `src/hooks/use-modal-store.ts`

#### API Communication

- **`src/lib/api-client.ts`** - Generic HTTP client with error handling
  - `apiClient` - Low-level fetch wrapper with auth headers
  - `backendApi` - Typed backend endpoint calls
  - `apiKeysApi` - API key management endpoints
- **`src/lib/api.ts`** - Backend API integration
  - Project/thread management
  - SSE streaming for real-time agent communication
  - Custom error classes: `BillingError`, `AgentRunLimitError`, `AgentCountLimitError`
- **Backend URL**: All API calls go to `NEXT_PUBLIC_BACKEND_URL` (default: `http://localhost:8000/api`)

#### Authentication

Custom auth system (NOT Supabase):
- Client-side: `src/lib/auth/client.ts`
- Session stored in localStorage
- Token refresh handled automatically
- Required backend endpoints:
  - `POST /auth/login` - Email/password login
  - `POST /auth/register` - User registration
  - `POST /auth/refresh` - Token refresh
  - `POST /auth/logout` - User logout
  - `GET /auth/me` - Current user info

#### Message Types & Streaming

The application handles unified message types from the backend:

```typescript
// src/components/thread/types.ts
interface UnifiedMessage {
  message_id: string | null;
  thread_id: string;
  type: 'user' | 'assistant' | 'tool' | 'system' | 'status' | 'browser_state';
  is_llm_message: boolean;
  content: string; // Always JSON string from backend
  metadata: string; // Always JSON string from backend
  created_at: string;
  agent_id?: string | null;
}
```

- Messages stream via SSE from backend
- Tool calls are tracked and displayed in side panels
- Tool results use structured format: `{ tool_name, parameters, result }`

#### Tool Call System

Tool calls are parsed and rendered with custom viewers:

- **Tool parsing**: `src/lib/utils/tool-parser.ts` - Extracts tool name, parameters, results
- **Tool views**: `src/components/thread/tool-views/` - Renderers for each tool type
  - Registry: `tool-views/wrapper/ToolViewRegistry.tsx`
  - Individual views for screenshots, bash, web searches, etc.
- **Side panel**: `src/components/thread/tool-call-side-panel.tsx` - Interactive tool result viewer
- **Hook**: `src/app/(dashboard)/projects/[projectId]/thread/_hooks/useToolCalls.ts`

### UI Components

- **shadcn/ui** components in `src/components/ui/`
- **Radix UI** primitives for accessibility
- **Tailwind CSS** for styling (v4)
- **Framer Motion** for animations
- **Lucide React** for icons

### Key Configuration Files

- **`next.config.ts`** - PostHog proxy rewrites for analytics
- **`tsconfig.json`** - Path aliases: `@/*` → `./src/*`
- **`tailwind.config.ts`** - Theme configuration
- **`eslint.config.mjs`** - Linting rules

## Common Patterns

### Making API Calls

```typescript
// Using backendApi for typed calls
import { backendApi } from '@/lib/api-client';

const { data, error, success } = await backendApi.get<ResponseType>('/endpoint');
if (!success) {
  // Error is automatically handled and displayed
  return;
}
```

### Using React Query

```typescript
import { useQuery, useMutation } from '@tanstack/react-query';

// Query
const { data, isLoading } = useQuery({
  queryKey: ['projects', projectId],
  queryFn: () => fetchProject(projectId),
});

// Mutation
const mutation = useMutation({
  mutationFn: updateProject,
  onSuccess: () => queryClient.invalidateQueries(['projects']),
});
```

### Tool Result Parsing

Tool results from the backend follow this structure:

```typescript
// New format from backend
{
  "tool_name": "bash",
  "xml_tag_name": "bash",
  "parameters": { "command": "ls -la" },
  "result": "output here"
}
```

Use `parseToolContent()` in `useToolCalls.ts` for parsing.

### Handling Streaming Messages

SSE streams provide real-time updates:
- Status messages (agent thinking, running)
- Message chunks (streaming LLM responses)
- Tool calls and results
- Browser state updates

## Subscription & Billing

Environment-aware subscription tiers configured in `src/lib/config.ts`:
- Staging vs Production price IDs
- Monthly, yearly, and yearly commitment plans
- Plan change validation (prevents downgrades)
- Helper functions: `isMonthlyPlan()`, `isYearlyPlan()`, `isPlanChangeAllowed()`

## Analytics & Monitoring

- **PostHog** - Product analytics (proxy configured in next.config.ts)
- **Vercel Analytics** - Performance monitoring
- **Google Analytics** - Web analytics
- **React Scan** - Development performance profiling

## File Paths & TypeScript

Always use path aliases:
```typescript
import { Component } from '@/components/ui/component';
import { apiClient } from '@/lib/api-client';
```

## Workflows

The application includes a visual workflow builder (`src/components/workflows/`) for creating multi-step agent automation flows with:
- Drag-and-drop node interface (@dnd-kit)
- MCP (Model Context Protocol) configuration
- Credential profile management
- Workflow execution dialogs
