"""The one Celery app instance, imported by job-worker's entrypoint and by
agent-core (to enqueue tasks) — same app, different processes.
"""

from celery import Celery

from jobpilot_shared.config import settings

celery_app = Celery(
    "jobpilot",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["jobpilot_shared.tasks"],
)

celery_app.conf.update(
    task_acks_late=True,          # ack after the task runs, not on receipt — safe under worker crash
    worker_prefetch_multiplier=1,  # don't hoard tasks a worker hasn't started yet
    task_track_started=True,
)
