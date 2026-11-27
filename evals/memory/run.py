"""Freeze a LongMemEval slice, retrieve evidence and compare reports."""

import argparse
import asyncio
import json
import os
import subprocess
import sys
from contextlib import AsyncExitStack
from pathlib import Path
from time import perf_counter
from uuid import UUID, uuid4

import httpx
from adapters import check_mem0_config, hindsight, local_url, mem0
from dataset import (
    Manifest,
    fingerprint,
    load_cases,
    make_case,
    read_dataset,
    sample_ids,
)
from pydantic import ValidationError
from report import ARMS, Header, Result, compare
from retrieval import Retrieved, bm25, fit_evidence, score

BACKEND = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND))


def prepare(args: argparse.Namespace) -> None:
    digest, records = read_dataset(args.dataset)
    manifest = Manifest(
        dataset_sha256=digest,
        seed=args.seed,
        case_ids=sample_ids(records, args.limit, args.seed),
        top_k=args.top_k,
        evidence_chars=args.evidence_chars,
    )
    cases = [make_case(records[key]) for key in manifest.case_ids]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as stream:
        stream.write(manifest.model_dump_json(indent=2) + "\n")
    sessions = sum(len(case.query.sessions) for case in cases)
    print(
        json.dumps(
            {
                "cases": len(cases),
                "sessions_per_arm": sessions,
                "future_sessions_excluded": sum(case.future_sessions for case in cases),
                "transcript_utf8_bytes_per_arm": sum(
                    len(session.text.encode()) for case in cases for session in case.query.sessions
                ),
                "max_answer_calls_per_arm": len(cases),
                "possible_remote_retains_per_arm": sessions,
                "manifest": fingerprint(manifest),
            }
        )
    )


def git_sha(path: Path = BACKEND) -> str:
    return subprocess.check_output(
        ["/usr/bin/env", "git", "rev-parse", "HEAD"], cwd=path, text=True
    ).strip()


async def retrieve(args: argparse.Namespace) -> int:
    manifest = Manifest.model_validate_json(args.manifest.read_bytes())
    cases = load_cases(args.dataset, manifest)
    backend = BACKEND
    legacy = args.arm == "agenticos-legacy"
    if legacy:
        if args.legacy_checkout is None:
            raise ValueError("Provide an existing pre-MVP worktree via --legacy-checkout.")
        backend = (args.legacy_checkout / "backend").resolve()
        if not (backend / "app").is_dir():
            raise ValueError("Legacy checkout does not contain backend/app.")
        sys.path.insert(0, str(backend))
    header = Header(
        manifest=fingerprint(manifest),
        arm=args.arm,
        label=args.label,
        git_sha=git_sha(backend),
        top_k=manifest.top_k,
        evidence_chars=manifest.evidence_chars,
        case_ids=manifest.case_ids,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    failures = 0
    run_id = uuid4().hex
    async with AsyncExitStack() as stack:
        if args.arm in {
            "agenticos-ledger",
            "agenticos-legacy",
            "agenticos-maintenance",
        }:
            from ledger import disposable_engine, replay

            engine = disposable_engine(os.environ.get("MEMORY_BENCH_AGENTICOS_DSN", ""))
            stack.push_async_callback(engine.dispose)
        if args.arm == "agenticos-maintenance":
            from maintenance import check_setup, replay_maintenance

            if not args.allow_service_calls or not args.maintenance_agent or not args.extract_model:
                raise ValueError(
                    "Maintenance requires --allow-service-calls, --maintenance-agent and --extract-model."
                )
            starter = await check_setup(engine, args.maintenance_agent, args.extract_model)
        if args.arm in {"mem0", "hindsight"}:
            if not args.allow_service_calls or not args.url:
                raise ValueError("Pass --url and --allow-service-calls for competitor arms.")
            headers = {}
            if args.arm == "mem0" and (key := os.environ.get("MEMORY_BENCH_MEM0_API_KEY")):
                headers["X-API-Key"] = key
            if args.arm == "hindsight" and (
                key := os.environ.get("MEMORY_BENCH_HINDSIGHT_API_KEY")
            ):
                headers["Authorization"] = f"Bearer {key}"
            client = await stack.enter_async_context(
                httpx.AsyncClient(
                    base_url=local_url(args.url),
                    headers=headers,
                    timeout=args.timeout,
                    trust_env=False,
                )
            )
        if args.arm == "mem0" and args.extract_model:
            await check_mem0_config(client, args.extract_model)
        with args.out.open("x", encoding="utf-8") as out:
            print(header.model_dump_json(), file=out, flush=True)
            for number, case in enumerate(cases, 1):
                row = Result(
                    question_id=case.id,
                    category=case.category,
                    question=case.query.question,
                    date=case.query.date,
                    evidence=[],
                    ingest_ms=None,
                    recall_ms=None,
                    cost_usd=None,
                    metrics={},
                )
                try:
                    scope = f"memory-bench-{run_id}-{number}"
                    if args.arm == "bm25":
                        started = perf_counter()
                        evidence = bm25(case.query, manifest.top_k)
                        result = Retrieved(evidence, 0, (perf_counter() - started) * 1_000, 0)
                    elif args.arm in {"agenticos-ledger", "agenticos-legacy"}:
                        result = await replay(engine, case.query, manifest.top_k, legacy=legacy)
                    elif args.arm == "agenticos-maintenance":
                        result = await replay_maintenance(
                            engine, starter, case.query, manifest.top_k
                        )
                    else:
                        adapter = mem0 if args.arm == "mem0" else hindsight
                        result = await adapter(client, case.query, scope, manifest.top_k)
                    row.evidence = fit_evidence(
                        result.evidence, manifest.top_k, manifest.evidence_chars
                    )
                    row.metrics = score(case, row.evidence)
                    row.ingest_ms, row.recall_ms, row.cost_usd = (
                        result.ingest_ms,
                        result.recall_ms,
                        result.cost_usd,
                    )
                except httpx.HTTPStatusError as error:
                    row.technical_error = f"HTTP {error.response.status_code}"
                except (httpx.RequestError, ValidationError, ValueError) as error:
                    row.technical_error = type(error).__name__
                print(row.model_dump_json(), file=out, flush=True)
                if row.technical_error:
                    failures += 1
                    print(f"{case.id}: {row.technical_error}", file=sys.stderr)
                    if failures == args.max_errors or row.technical_error in {
                        "HTTP 401",
                        "HTTP 402",
                        "HTTP 403",
                        "HTTP 404",
                        "ConnectError",
                    }:
                        return 1
    return int(bool(failures))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    prepare_args = commands.add_parser("prepare")
    prepare_args.add_argument("--dataset", type=Path, required=True)
    prepare_args.add_argument("--out", type=Path, required=True)
    prepare_args.add_argument("--limit", type=int, required=True)
    prepare_args.add_argument("--seed", type=int, default=17)
    prepare_args.add_argument("--top-k", type=int, default=8)
    prepare_args.add_argument("--evidence-chars", type=int, default=12_000)
    retrieve_args = commands.add_parser("retrieve")
    for name in ("dataset", "manifest", "out"):
        retrieve_args.add_argument(f"--{name}", type=Path, required=True)
    retrieve_args.add_argument("--arm", required=True, choices=ARMS)
    retrieve_args.add_argument(
        "--label", required=True, help="Pin service revision and configuration."
    )
    retrieve_args.add_argument("--legacy-checkout", type=Path)
    retrieve_args.add_argument("--url")
    retrieve_args.add_argument("--extract-model", help="Verify the OpenRouter model at low effort.")
    retrieve_args.add_argument(
        "--maintenance-agent", type=UUID, help="Published disposable starter ID."
    )
    retrieve_args.add_argument("--allow-service-calls", action="store_true")
    retrieve_args.add_argument("--timeout", type=float, default=300)
    retrieve_args.add_argument("--max-errors", type=int, default=3)
    compare_args = commands.add_parser("compare")
    compare_args.add_argument("reports", type=Path, nargs="+")
    compare_args.add_argument("--grade", type=Path, action="append", default=[])
    return root


def main() -> int:
    root = parser()
    args = root.parse_args()
    if args.command == "retrieve" and (args.timeout <= 0 or args.max_errors <= 0):
        root.error("Timeout and maximum error count must be positive.")
    try:
        if args.command == "prepare":
            prepare(args)
        elif args.command == "retrieve":
            return asyncio.run(retrieve(args))
        else:
            print(json.dumps(compare(args.reports, args.grade), indent=2))
    except httpx.HTTPStatusError as error:
        root.exit(2, f"Benchmark setup failed with HTTP {error.response.status_code}.\n")
    except httpx.RequestError as error:
        root.exit(2, f"Benchmark setup failed: {type(error).__name__}.\n")
    except (ValueError, TypeError, OSError, KeyError) as error:
        root.exit(2, f"Benchmark input error: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
