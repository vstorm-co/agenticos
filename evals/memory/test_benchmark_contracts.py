"""Test benchmark mechanics on invented records and mocked HTTP only."""

import json
import tempfile
import unittest
from pathlib import Path

import httpx
from adapters import hindsight, local_url, mem0
from answer import request_content
from dataset import Manifest, fingerprint, load_cases, make_case, read_dataset, sample_ids
from report import Header, Result, compare
from retrieval import Evidence, bm25, fit_evidence, score


def fixture(case_id: str = "synthetic", *, abstain: bool = False) -> dict[str, object]:
    return {
        "question_id": case_id,
        "question_type": "temporal-reasoning",
        "question": "How large was Atlas?",
        "answer": "SECRET GOLD TEXT",
        "question_date": "2020/03/10 (Tue) 15:00",
        "haystack_session_ids": ["answer_future", "answer_second", "answer_first"],
        "haystack_dates": ["2020/03/11", "2020/03/10", "2020/01/01"],
        "haystack_sessions": [
            [{"role": "user", "content": "Atlas: 40"}],
            [{"role": "assistant", "content": "Atlas: 20", "has_answer": True}],
            [{"role": "user", "content": "Atlas: two divisions"}],
        ],
        "answer_session_ids": [] if abstain else ["answer_first", "answer_second"],
    }


def row_with(evidence: list[Evidence]) -> Result:
    case = make_case(fixture())
    return Result(
        question_id=case.id,
        category=case.category,
        question=case.query.question,
        date=case.query.date,
        evidence=evidence,
        ingest_ms=1,
        recall_ms=3,
        cost_usd=0.0,
        metrics=score(case, evidence),
    )


class CaseTests(unittest.TestCase):
    def test_manifest_hash_and_order(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / "data.json"
            path.write_text(json.dumps([fixture(), fixture("negative_abs", abstain=True)]))
            digest, records = read_dataset(path)
            chosen = sample_ids(records, 2, 17)
            self.assertEqual(chosen, sample_ids(dict(reversed(list(records.items()))), 2, 17))
            manifest = Manifest(
                dataset_sha256=digest, seed=17, case_ids=chosen, top_k=4, evidence_chars=400
            )
            self.assertEqual([case.id for case in load_cases(path, manifest)], chosen)
            with path.open("a") as out:
                out.write("\n")
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                load_cases(path, manifest)

    def test_historical_cutoff_preserves_gold_and_blinds_answerer(self) -> None:
        data = fixture()
        case = make_case(data)
        self.assertEqual(case.future_sessions, 1)
        self.assertEqual(case.gold, {"s00001", "s00002"})
        evidence = bm25(case.query, 4)
        text = request_content(row_with(evidence))
        for secret in ("SECRET GOLD TEXT", "answer_first", "Atlas: 40", "has_answer"):
            self.assertNotIn(secret, text)
        data["answer_session_ids"] = ["answer_future"]
        with self.assertRaisesRegex(ValueError, "missing before the cutoff"):
            make_case(data)

    def test_budget_and_provenance_metrics(self) -> None:
        case = make_case(fixture())
        evidence = fit_evidence(
            [Evidence(source_id="wrong", text="xy"), Evidence(source_id="s00001", text="answer")],
            top_k=5,
            budget=4,
        )
        self.assertEqual([entry.text for entry in evidence], ["xy", "an"])
        result = score(case, evidence)
        self.assertEqual(result["recall"], 0.5)
        self.assertEqual(result["mrr"], 0.5)
        self.assertEqual(result["all_evidence"], 0)
        self.assertEqual(result["provenance"], 0.5)
        negative = make_case(fixture("negative_abs", abstain=True))
        self.assertIsNone(score(negative, [])["recall"])

    def test_paired_comparison_and_official_grading_input(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            manifest = Manifest(
                dataset_sha256="hash", seed=17, case_ids=["synthetic"], top_k=5, evidence_chars=50
            )
            base = Header(
                manifest=fingerprint(manifest),
                arm="bm25",
                label="baseline",
                git_sha="a",
                top_k=5,
                evidence_chars=50,
                case_ids=["synthetic"],
            )
            report, candidate, grade = (root / name for name in ("base", "candidate", "grade"))
            report.write_text(base.model_dump_json() + "\n" + row_with([]).model_dump_json())
            other = base.model_copy(update={"arm": "hindsight", "label": "candidate"})
            exact = Evidence(source_id="s00002", text="Atlas: 20")
            candidate.write_text(
                other.model_dump_json() + "\n" + row_with([exact]).model_dump_json()
            )
            grade.write_text(
                json.dumps(
                    {
                        "question_id": "synthetic",
                        "autoeval_label": {"label": True, "model": "judge"},
                    }
                )
            )
            result = compare([report, candidate], [grade, grade])
            self.assertEqual(result["arms"][1]["recall_delta_vs_first_95pct_ci"]["delta"], 0.5)
            self.assertEqual(result["arms"][1]["answer_accuracy"], 1.0)
            candidate.write_text(
                other.model_copy(update={"top_k": 6}).model_dump_json()
                + "\n"
                + row_with([exact]).model_dump_json()
            )
            with self.assertRaisesRegex(ValueError, "same frozen cases and evidence budget"):
                compare([report, candidate], [])


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    def test_loopback_only(self) -> None:
        for address in ("https://example.com", "http://localhost@other", "http://localhost/path"):
            with self.assertRaises(ValueError):
                local_url(address)

    async def test_mem0_scope_and_provenance(self) -> None:
        query = make_case(fixture()).query
        requests = []

        def handle(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            requests.append((request.url.path, body))
            if request.url.path == "/memories":
                return httpx.Response(200, json={"results": []})
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"memory": "Atlas: 20", "metadata": {"source_session": "s00002"}},
                        {"memory": "unattributed", "metadata": {"source_session": "s99999"}},
                    ]
                },
            )

        async with httpx.AsyncClient(
            base_url="http://localhost:8000", transport=httpx.MockTransport(handle)
        ) as client:
            result = await mem0(client, query, "test-scope", 2)
        self.assertEqual(requests[0][1]["user_id"], "test-scope")
        self.assertEqual(requests[1][1]["metadata"]["source_session"], "s00002")
        self.assertEqual(requests[2][1]["filters"], {"user_id": "test-scope"})
        self.assertEqual([item.source_id for item in result.evidence], ["s00002", None])
        self.assertIsNone(result.cost_usd)

    async def test_hindsight_uses_sync_retain_and_query_clock(self) -> None:
        query = make_case(fixture()).query
        requests = []

        def handle(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            requests.append((request.url.path, body))
            if request.url.path.endswith("/recall"):
                return httpx.Response(
                    200, json={"results": [{"text": "Atlas: 20", "document_id": "s00002"}]}
                )
            return httpx.Response(200, json={"success": True, "async": False, "items_count": 1})

        async with httpx.AsyncClient(
            base_url="http://localhost:8888", transport=httpx.MockTransport(handle)
        ) as client:
            result = await hindsight(client, query, "run-bank", 2)
        self.assertEqual(requests[0][0], "/v1/default/banks/run-bank/memories")
        self.assertFalse(requests[0][1]["async"])
        self.assertEqual(requests[-1][1]["query_timestamp"], query.date.isoformat())
        self.assertEqual(result.evidence[0].source_id, "s00002")


class AnswerTests(unittest.IsolatedAsyncioTestCase):
    async def test_budget_preflight_and_official_hypothesis_shape(self) -> None:
        from argparse import Namespace
        from decimal import Decimal
        from unittest.mock import patch

        from answer import generate

        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            args = Namespace(
                retrieval=root / "retrieval",
                out=root / "hypothesis",
                usage=root / "usage",
                model="fixture-model",
                input_per_million=Decimal("10"),
                output_per_million=Decimal("20"),
                max_usd=Decimal(0),
                max_output_tokens=50,
                estimate_only=False,
            )
            header = Header(
                manifest="fixture",
                arm="bm25",
                label="baseline",
                git_sha="a",
                top_k=5,
                evidence_chars=50,
                case_ids=["synthetic"],
            )
            args.retrieval.write_text(
                header.model_dump_json() + "\n" + row_with([]).model_dump_json()
            )
            requests: list[dict[str, object]] = []

            def handle(request: httpx.Request) -> httpx.Response:
                requests.append(json.loads(request.content))
                return httpx.Response(
                    200,
                    json={
                        "model": "fixture-model-v1",
                        "choices": [{"message": {"content": "No evidence."}}],
                        "usage": {"prompt_tokens": 10, "completion_tokens": 3},
                    },
                )

            client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
            with (
                patch.dict(
                    "os.environ",
                    {"MEMORY_BENCH_ANSWER_URL": "http://localhost/v1/chat/completions"},
                ),
                patch("answer.httpx.AsyncClient", return_value=client),
            ):
                with self.assertRaisesRegex(ValueError, "planned spend"):
                    await generate(args)
                self.assertFalse(requests)
                self.assertFalse(args.out.exists())
                args.max_usd = Decimal("1")
                await generate(args)
            self.assertEqual(len(requests), 1)
            self.assertEqual(requests[0]["max_completion_tokens"], 50)
            self.assertEqual(
                json.loads(args.out.read_text()),
                {
                    "question_id": "synthetic",
                    "hypothesis": "No evidence.",
                },
            )
            self.assertEqual(
                Decimal(json.loads(args.usage.read_text().splitlines()[1])["cost_usd"]),
                Decimal("0.00016"),
            )


class ModelComparisonTests(unittest.TestCase):
    def test_summary_separates_quality_technical_and_missing_rows(self) -> None:
        from decimal import Decimal

        from compare_models import HAIKU, Phase, Receipt, summarize

        rows = [
            Receipt(
                case="pass",
                model=HAIKU,
                errors=[],
                latency_ms=100,
                cost_usd=Decimal("0.001"),
                cost_is_partial=False,
            ),
            Receipt(case="wrong", model=HAIKU, errors=["unexpected claim"], latency_ms=200),
            Receipt(
                case="provider",
                model=HAIKU,
                errors=["technical: Model HTTP 429"],
                latency_ms=300,
            ),
        ]
        result = summarize([Phase("extraction", 4, rows, 0.8, 1, "fixture.jsonl")])
        self.assertEqual(
            (
                result["passed"],
                result["quality_failures"],
                result["technical_failures"],
                result["missing"],
            ),
            (1, 1, 1, 1),
        )
        self.assertEqual(result["pass_rate"], 0.25)
        self.assertEqual(result["cost_usd_known"], "0.001")
        self.assertFalse(result["cost_complete"])
        self.assertEqual((result["case_p50_ms"], result["case_p95_ms"]), (200, 300))
