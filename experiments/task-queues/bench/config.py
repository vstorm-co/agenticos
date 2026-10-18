"""Settings every backend and the driver read, from the environment."""

import os

POSTGRES_DSN = os.environ.get("BENCH_POSTGRES_DSN", "postgresql://bench:bench@postgres:5432/bench")
REDIS_URL = os.environ.get("BENCH_REDIS_URL", "redis://redis:6379/0")
BACKEND = os.environ.get("BENCH_BACKEND", "")

# How many tasks one worker process runs at once, where the backend has the knob.
CONCURRENCY = int(os.environ.get("BENCH_CONCURRENCY", "20"))

# Seconds between scheduled sweeps. One minute is what production uses.
SWEEP_SECONDS = int(os.environ.get("BENCH_SWEEP_SECONDS", "60"))

# Import the real application in every task process, as production does.
IMPORT_APP = os.environ.get("BENCH_IMPORT_APP", "1") == "1"

SAMPLES_DIR = os.environ.get("BENCH_SAMPLES_DIR", "/bench/samples")

# The current run's label, so a scheduled sweep files itself under it.
RUN_LABEL = os.environ.get("BENCH_RUN_LABEL", "adhoc")
