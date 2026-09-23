"""Shared code between agent-core (FastAPI) and job-worker (Celery).

Same codebase, two deployment targets: agent-core imports this package to
serve the API, job-worker imports it to run the Celery worker process. Keeping
config, DB clients, and task *definitions* here (rather than duplicated in
each service) is what makes "same codebase, different deployment target" true
rather than aspirational.
"""
