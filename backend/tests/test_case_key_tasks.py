"""The worker's half of a case's drafted keys: the job hands its draft to the service."""

import uuid
from unittest.mock import AsyncMock

import pytest

from app.db.models.case_key_draft import CaseKeyDraft
from app.services import case_key_draft
from app.worker.jobs import ExtractCaseKeys
from app.worker.tasks import case_key_tasks

pytestmark = pytest.mark.anyio


async def test_the_job_drafts_its_keys_and_a_lost_one_settles(monkeypatch) -> None:
    extract, settle = AsyncMock(), AsyncMock()
    monkeypatch.setattr(case_key_draft, "extract_case_keys", extract)
    monkeypatch.setattr(case_key_draft, "settle_lost", settle)
    job = ExtractCaseKeys(draft_id=uuid.uuid4(), organization_id=uuid.uuid4())

    await case_key_tasks.extract_case_keys(job)
    await case_key_tasks.settle_lost_draft(job, "timed out")

    extract.assert_awaited_once_with(job.draft_id, job.organization_id)
    settle.assert_awaited_once_with(job.draft_id, job.organization_id)


def test_a_draft_names_its_case_and_status() -> None:
    case = uuid.uuid4()

    assert repr(CaseKeyDraft(case_id=case, status="ready")) == (
        f"<CaseKeyDraft(case={case}, status=ready)>"
    )
