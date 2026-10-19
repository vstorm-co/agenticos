"""Background work: the job queue's worker, its schedules and the tasks it runs (#2219).

Nothing is imported here on purpose: a service that enqueues a job imports
`app.worker.jobs` and must not pull the worker's runtime in with it.
"""
