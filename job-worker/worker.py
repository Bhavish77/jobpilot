"""Job Worker entrypoint.

Same codebase as agent-core (both import jobpilot_shared) — this file is the
thin difference: agent-core runs uvicorn against an ASGI app, this runs the
Celery worker process against the same `celery_app` + `tasks` module.

Run with: celery -A worker.celery_app worker --loglevel=info
"""

from jobpilot_shared.celery_app import celery_app
from jobpilot_shared import job_tasks, prepare_tasks  # noqa: F401 - import registers the tasks

__all__ = ["celery_app"]
