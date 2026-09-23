"""Placeholder Celery tasks for the prepare-application pipeline.

Ordering (Phase 2 decision, carried over from design doc):
  Resume -> Cover Letter   run sequentially   (cover letter references the resume)
  Interview Prep           runs in parallel   (only needs the JD + candidate background)

Real orchestration (Phase 4) looks like:

    from celery import chain, group, chord

    workflow = chord(
        group(
            chain(generate_resume.s(job_id), generate_cover_letter.s()),
            generate_interview_prep.s(job_id),
        ),
        mark_ready_to_apply.s(job_id),
    )
    workflow.apply_async()

Every task here still needs, before Phase 4 is done: an LLM-call wrapper with
circuit breaker + retry/backoff/jitter + timeout, an `acquire_llm_permit()`
call before the actual LLM request, and idempotency (safe to run twice if
Celery redelivers the task).
"""

from jobpilot_shared.celery_app import celery_app


@celery_app.task(name="jobpilot.generate_resume")
def generate_resume(job_id: str) -> dict:
    # TODO Phase 4: acquire_llm_permit(), call the Resume Agent, persist to Postgres.
    return {"job_id": job_id, "stage": "resume", "status": "not_implemented"}


@celery_app.task(name="jobpilot.generate_cover_letter")
def generate_cover_letter(resume_result: dict) -> dict:
    # TODO Phase 4: use resume_result to keep tone/emphasis consistent.
    return {**resume_result, "stage": "cover_letter", "status": "not_implemented"}


@celery_app.task(name="jobpilot.generate_interview_prep")
def generate_interview_prep(job_id: str) -> dict:
    # TODO Phase 4: runs in parallel with the resume/cover-letter chain above.
    return {"job_id": job_id, "stage": "interview_prep", "status": "not_implemented"}


@celery_app.task(name="jobpilot.mark_ready_to_apply")
def mark_ready_to_apply(results: list, job_id: str) -> dict:
    # TODO Phase 4/5: flip the Pipeline card to "Ready to apply" and publish
    # a Redis pub/sub event so Notify can push it over WebSocket.
    return {"job_id": job_id, "stage": "ready_to_apply", "results": results}
