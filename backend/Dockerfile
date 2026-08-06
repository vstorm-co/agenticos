
# Build stage
FROM python:3.12-slim AS builder

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

# Install dependencies
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev

# Copy application
COPY . /app

# Install project
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


# Runtime stage
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
# LiteParse converts non-PDF documents to PDF before parsing, and the two
# conversion paths need different things present:
#
#   - office formats (.docx, .xlsx, .pptx, .odt, .csv, ...) shell out to
#     LibreOffice. Without it, uploading a spreadsheet to a LiteParse collection
#     fails at conversion — so it is installed rather than left to the operator.
#     `libreoffice-core` + the three filters is roughly a third of the full
#     `libreoffice` package and covers every format we advertise.
#   - images (.png, .jpg, .tiff, ...) are converted by liteparse's own Rust
#     code and need nothing installed.
#
# `tesseract-ocr` is the OCR engine behind `ocr: true`; the language packs are
# what `ocr_language` selects between, and a code with no pack installed is a
# parse that returns nothing. English and Polish are shipped — add
# `tesseract-ocr-<lang>` here for others.
#
# No Node.js: the `liteparse` PyPI package ships its own native binary (PyO3).
# The npm CLI this used to install was never on the code path.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-core libreoffice-writer libreoffice-calc libreoffice-impress \
    tesseract-ocr tesseract-ocr-eng tesseract-ocr-pol \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app /app

# Add venv to path
ENV PATH="/app/.venv/bin:$PATH"

# Create non-root user and writable directories
RUN adduser --disabled-password --gecos "" appuser && \
    mkdir -p /app/media /app/data /app/chroma_data /app/models_cache && \
    chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# No HEALTHCHECK here, deliberately. This image has two consumers with different
# commands: the API (`uvicorn app.main:app`) and the Prefect runner
# (`python -m app.worker.prefect_app`). The probe that used to live here asked
# localhost:8000 for `/api/v1/health`, which the runner serves nothing on - so the
# runner was `unhealthy` from the second it started and stayed that way, hiding
# the one thing a health status exists to show. An image cannot know which of the
# two it was started as; a service definition does. Both probes are in the compose
# files, one per service.
CMD ["python", "-m", "cli.commands", "server", "run", "--host", "0.0.0.0", "--port", "8000"]
