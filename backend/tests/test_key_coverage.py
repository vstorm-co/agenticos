"""What a coverage report reads from a dataset and shows the source coverage agent."""

import uuid
from unittest.mock import AsyncMock

import pytest

from app.db.models.key_coverage_report import KeyCoverageReport
from app.schemas.scoring import MAX_KEYS
from app.services import key_coverage
from app.services.key_coverage import PROMPT_CHARS, _prompt, key_labels, passages
from app.worker.jobs import ReportKeyCoverage
from app.worker.tasks import key_coverage_tasks

pytestmark = pytest.mark.anyio


class TestKeyLabels:
    def test_each_label_is_read_once_trimmed_and_never_a_value(self) -> None:
        checks = [
            [
                {"type": "contains", "value": "INV"},
                {"type": "keys", "keys": [{"key": " Total ", "value": "913.68"}]},
            ],
            [
                {
                    "type": "keys",
                    "keys": [{"key": "TOTAL", "value": "1"}, {"key": "Due", "value": "x"}],
                }
            ],
        ]

        assert key_labels(checks) == ["Total", "Due"]

    def test_a_malformed_stored_check_is_skipped(self) -> None:
        checks = [
            [
                {"type": "keys", "keys": "Total"},
                {"type": "keys", "keys": ["Total", {"key": 7}, {"key": "  "}, {"key": "Due"}]},
            ]
        ]

        assert key_labels(checks) == ["Due"]

    def test_labels_stop_at_the_keys_a_check_may_hold(self) -> None:
        keys = [{"key": f"Key {number}", "value": "v"} for number in range(MAX_KEYS + 5)]

        assert len(key_labels([[{"type": "keys", "keys": keys}]])) == MAX_KEYS


class TestPassages:
    def test_each_mention_is_read_once_around_the_label(self) -> None:
        text = "Due date first. " + "x" * 400 + " The due DATE again. " + "y" * 400 + " due date"

        found = passages(text, "Due date")

        assert len(found) == 2
        assert found[0].startswith("Due date first.")
        assert "due DATE again" in found[1]

    def test_a_label_never_named_has_no_passage(self) -> None:
        assert passages("Nothing here", "Total") == []


class TestPrompt:
    def test_an_agent_without_sources_is_said_to_have_none(self) -> None:
        assert _prompt(["Total"], []).endswith("The agent has no sources.")

    def test_material_past_the_limit_is_cut_and_the_prompt_says_so(self) -> None:
        prompt = _prompt(["Total"], ["x" * PROMPT_CHARS])

        assert prompt.endswith("[The rest of the material was cut for length.]")
        assert len(prompt) < PROMPT_CHARS + 100


def test_a_report_names_its_agent_and_status() -> None:
    agent = uuid.uuid4()

    assert repr(KeyCoverageReport(agent_id=agent, status="ready")) == (
        f"<KeyCoverageReport(agent={agent}, status=ready)>"
    )


async def test_the_job_judges_its_report_and_a_lost_one_settles(monkeypatch) -> None:
    judge, settle = AsyncMock(), AsyncMock()
    monkeypatch.setattr(key_coverage, "report_key_coverage", judge)
    monkeypatch.setattr(key_coverage, "settle_lost", settle)
    job = ReportKeyCoverage(report_id=uuid.uuid4(), organization_id=uuid.uuid4())

    await key_coverage_tasks.report_key_coverage(job)
    await key_coverage_tasks.settle_lost_report(job, "timed out")

    judge.assert_awaited_once_with(job.report_id, job.organization_id)
    settle.assert_awaited_once_with(job.report_id, job.organization_id)
