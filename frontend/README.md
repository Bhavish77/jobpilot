# frontend/

Next.js (App Router, TypeScript, Tailwind v4) dashboard UI — built in
Phase 6, designed fresh rather than from the earlier "JobPilot Screens"
mockup artifact. See `../docs/PHASE_6_PLAN.md` for the full build record
(scope corrections, the real backend gaps found and fixed first, the
WCAG-checked design system, verification notes per chunk) and
`../CLAUDE.md` for how to run it locally.

Dev-native, not containerized — runs directly with `npm run dev`, against
agent-core/notify's published Docker ports over localhost like any other
client of those APIs. Revisit containerizing it in Phase 7 if production
deployment needs it.

## Structure

- `app/` — routes. `(app)/` is the auth-gated route group (Discover,
  Pipeline, the Job Workspace, Profile) sharing one layout (sidebar + auth
  check); `/`, `/login`, `/register`, `/style-guide` are public.
- `components/ui/` — the primitive component library (Button, Card,
  Badge, Input, Tabs, ...), shadcn/ui-style: owned code, not a dependency.
- `components/` (top level) — app-specific composed components
  (sidebar, session/theme/toast providers, the Notify WebSocket listener).
- `lib/api.ts` — the typed fetch client every screen uses to talk to
  agent-core (`credentials: "include"` on every call — the session is an
  httpOnly cookie, never a token this code reads itself).
- `app/globals.css` — the design tokens (colors, radius) as CSS
  variables, light + dark, each pairing checked against the real WCAG 2.1
  contrast formula before being chosen.
