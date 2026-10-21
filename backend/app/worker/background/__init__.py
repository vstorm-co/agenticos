"""In-process work a request hands to FastAPI `BackgroundTasks`.

Runs inside the API worker process after the response is sent; see `channel`.
Work that must outlive a restart is a job (`app.services.background_jobs`), not here.
"""
