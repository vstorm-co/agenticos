# The AgenticOS backend image, plus every queue under comparison.
#
# Build from this directory: docker build -t tqbench:latest .
#
# Built FROM the real backend so a task process imports the real application:
# that import is the cost the comparison is about. Build the base first:
#   docker build -f backend/Dockerfile -t agenticos-backend:bench-base .
FROM agenticos-backend:bench-base

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Installed into the backend's own environment, beside its pinned packages, so a
# queue whose dependencies clash with AgenticOS's fails here rather than in a run.
RUN uv pip install --python /app/.venv/bin/python \
    "celery[redis]>=5.6" \
    "taskiq>=0.12,<0.13" "taskiq-redis>=1.0" \
    "hatchet-sdk>=1.0" \
    "procrastinate[psycopg]>=3.0" "psycopg[binary,pool]>=3.2" \
    "dramatiq[redis]>=1.17" \
    "saq[redis]>=0.22" \
    "docker>=7.1" \
    "psutil>=6.0"

COPY bench /bench/bench
COPY samples /bench/samples
ENV PYTHONPATH=/bench:/app
WORKDIR /bench
