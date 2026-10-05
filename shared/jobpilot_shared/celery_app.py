"""The one Celery app instance, imported by job-worker's entrypoint and by
agent-core (to enqueue tasks) — same app, different processes.
"""

from celery import Celery
from celery.schedules import crontab

from jobpilot_shared.config import settings

celery_app = Celery(
    "jobpilot",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["jobpilot_shared.job_tasks", "jobpilot_shared.prepare_tasks"],
)

celery_app.conf.update(
    task_acks_late=True,          # ack after the task runs, not on receipt — safe under worker crash
    worker_prefetch_multiplier=1,  # don't hoard tasks a worker hasn't started yet
    task_track_started=True,
    # Celery Beat is a separate process (run with `celery -A worker.celery_app
    # beat`) that just enqueues tasks on this schedule — the actual work
    # still runs on a normal worker, same as any other task.
    beat_schedule={
        "ingest-jobs-daily": {
            "task": "jobpilot.ingest_jobs",
            "schedule": crontab(hour=3, minute=0),  # 03:00 UTC daily
        },
    },
)
