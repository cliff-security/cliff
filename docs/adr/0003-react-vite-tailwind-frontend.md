# ADR-0003: React + TypeScript + Vite + Tailwind for the Frontend

**Date:** 2026-03-25
**Status:** Accepted

## Context

Cliff needs a web frontend with five pages (Queue, Workspace, History, Integrations, Settings). The Workspace page is the product center — a chat-led interface with a persistent sidebar, agent run cards, and markdown result rendering.

Requirements:

- Fast local development iteration
- Simple static build output (served by FastAPI in production)
- Strong AI-assisted development ergonomics
- Rich component ecosystem
- No SSR/SEO requirements (self-hosted internal app)

## Decision

Use **React 18+ with TypeScript**, **Vite** as the build tool, and **Tailwind CSS** for styling.

Additional libraries:

- React Router for navigation
- TanStack Query for API state management
- A component library (shadcn/ui or similar) for consistent UI primitives

Not Next.js — we don't need SSR, server components, or the added complexity for a self-hosted app.

## Consequences

- **Easier:** Vite provides sub-second HMR and simple build output.
- **Easier:** Large React ecosystem for markdown rendering, chat UIs, and data tables.
- **Easier:** Tailwind + shadcn/ui gives consistent design without custom CSS.
- **Harder:** Frontend and backend are separate dev servers during development (Vite on 5173, FastAPI on 8000). Solved with a dev proxy.
- **Harder:** Node.js 20+ required for development.
