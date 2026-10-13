"""`doctor`'s answer to "where do uploaded files live, and are they encrypted?".

One line of the sheet a security officer reads (#1423). Three things it must get
right, each of which is a wrong answer somebody could act on:

- **`local` is not a failure.** It is the default, and a deployment on one host
  with an encrypted volume is correctly configured. `doctor` exits non-zero on a
  failure, so calling this one would break every provisioning script that runs it.
- **`s3` with no bucket is.** Nothing can be stored, and the first upload is the
  only other place that would say so.
- **`s3` with encryption off is neither.** MinIO refuses SSE-S3 without a KES
  server, so it is a legitimate configuration - and it is not what the at-rest
  row in `docs/security.md` describes, so it must not read as healthy.
"""

from __future__ import annotations

import pytest

from app.commands.doctor import _file_storage
from app.core.config import settings


@pytest.fixture(autouse=True)
def _s3_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "FILE_STORAGE_S3_BUCKET", "agenticos-files")
    monkeypatch.setattr(settings, "FILE_STORAGE_S3_ENCRYPTION", "sse-s3")


def test_the_local_backend_is_reported_rather_than_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "FILE_STORAGE_BACKEND", "local")

    status, detail = _file_storage()

    assert status == "unconfigured"
    assert "encrypt the volume" in detail


def test_s3_with_no_bucket_is_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "FILE_STORAGE_BACKEND", "s3")
    monkeypatch.setattr(settings, "FILE_STORAGE_S3_BUCKET", "")

    status, detail = _file_storage()

    assert status == "unhealthy"
    assert "FILE_STORAGE_S3_BUCKET" in detail


def test_s3_with_encryption_names_the_bucket_and_the_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "FILE_STORAGE_BACKEND", "s3")

    status, detail = _file_storage()

    assert status == "healthy"
    assert "bucket=agenticos-files" in detail
    assert "encryption=sse-s3" in detail


def test_s3_with_encryption_off_does_not_read_as_healthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "FILE_STORAGE_BACKEND", "s3")
    monkeypatch.setattr(settings, "FILE_STORAGE_S3_ENCRYPTION", "none")

    status, detail = _file_storage()

    assert status == "unconfigured"
    assert "encryption=none" in detail
