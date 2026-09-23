# Notes

Personal learning notes, separate from `docs/` (which is JobPilot's own
design record). This is "explain it to me like I'll forget it by next week"
material — concepts that come up while building JobPilot but are general
enough to be worth remembering outside this one project.

One topic per file, grouped into subfolders by subject area. Add a line
below when you add a note, so this stays a working index.

## Topics

- **databases/**
  - [sync-vs-async-drivers.md](databases/sync-vs-async-drivers.md) — why
    `agent-core` uses `asyncpg` but Alembic migrations use `psycopg`, same
    Postgres either way.
