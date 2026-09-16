"""Run the load suite against a deployment and print the report.

    uv run --directory backend python ../loadtest/run.py --api-pid 12345 \
        > ../loadtest/results/$(date +%F)-laptop.md

What it needs in place first is in `docs/load-testing.md`: a migrated database, a
seeded fixture (`seed.py`), and the stub model answering. It refuses to start
without any of them rather than measuring a deployment that cannot do the work,
which is the failure that produces a green report about nothing.

Every phase and every rate is `scenario.py`'s; this file is the wiring.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
from pathlib import Path

import httpx
from driver import REQUEST_TIMEOUT, Traffic, drive, headers
from metrics import Recorder
from probes import Probes, sample_forever
from report import render
from scenario import MIX, PHASES, Phase
from seed import Fixture

HERE = Path(__file__).resolve().parent
SAMPLE_EVERY_SECONDS = 2.0


async def preflight(fixture: Fixture, client: httpx.AsyncClient) -> None:
    """Refuse to start against a deployment that cannot serve the fixture.

    Four questions, and each of them has been the reason a run was worthless:
    the API is not there; the token has expired; the agent was never published,
    so every run workload would refuse; the collection is empty, so every
    retrieval would answer in three milliseconds with nothing and look fast.
    """
    try:
        health = await client.get("/health", timeout=10.0)
    except httpx.HTTPError as failure:
        raise SystemExit(f"No API at {fixture.base_url}: {type(failure).__name__}") from failure
    if health.status_code != 200:
        raise SystemExit(f"The API at {fixture.base_url} answered {health.status_code}")

    agents = await client.get("/agents", params={"limit": 100}, headers=headers(fixture))
    if agents.status_code == 401:
        raise SystemExit("The fixture's token has expired. Re-run seed.py.")
    if agents.status_code != 200:
        raise SystemExit(f"GET /agents answered {agents.status_code}: {agents.text[:200]}")
    published = {
        str(row["id"]) for row in agents.json().get("items", []) if row.get("status") == "published"
    }
    if fixture.agent_id not in published:
        raise SystemExit(
            f"Agent {fixture.agent_id} has no published version, so every run would refuse. "
            "Re-run seed.py."
        )

    search = await client.post(
        "/rag/search",
        json={"collection_name": fixture.collection, "query": "procedure", "limit": 1},
        headers=headers(fixture),
    )
    if search.status_code != 200 or not search.json().get("results"):
        raise SystemExit(
            f"Collection {fixture.collection} returns nothing, so retrieval would be "
            "measured against an empty index. Re-run seed.py."
        )


async def measure(arguments: argparse.Namespace) -> str:
    """Drive the scenario and render what came back."""
    fixture = Fixture.from_json(Path(arguments.fixture).read_text(encoding="utf-8"))
    phases = _phases(arguments)
    async with httpx.AsyncClient(
        base_url=f"{fixture.base_url}/api/v1",
        timeout=REQUEST_TIMEOUT,
        limits=httpx.Limits(max_connections=arguments.connections),
    ) as client:
        await preflight(fixture, client)
        loop = asyncio.get_running_loop()
        recorder = Recorder()
        probes = Probes()
        started = loop.time()
        traffic = Traffic(
            fixture=fixture,
            client=client,
            recorder=recorder,
            started=started,
            random=random.Random(20260916),  # noqa: S311 - a reproducible run, not a secret
        )
        stop = asyncio.Event()
        sampler = asyncio.create_task(
            sample_forever(
                probes,
                pid=arguments.api_pid,
                database_url=arguments.database_url,
                started=started,
                every_seconds=SAMPLE_EVERY_SECONDS,
                stop=stop,
            )
        )
        try:
            await drive(traffic, phases=phases, mix=MIX, on_phase=_announce)
        finally:
            stop.set()
            await sampler
        seconds = loop.time() - started

    return render(
        recorder.samples,
        phases=phases,
        mix=MIX,
        probes=probes,
        seconds=seconds,
        title=arguments.title,
        topology=arguments.topology,
    )


def _announce(phase: Phase) -> None:
    """Say which phase started, on stderr, so stdout stays a clean report."""
    print(
        f"▶ {phase.name}: {phase.seconds:.0f}s at {phase.rate_per_second:.0f}/s",
        file=sys.stderr,
        flush=True,
    )


def _phases(arguments: argparse.Namespace) -> tuple[Phase, ...]:
    """The scenario's phases, optionally shortened for a smoke run.

    `--scale` multiplies every phase's duration and nothing else, so a tenth-scale
    run has the same rates and the same mix and simply measures fewer requests.
    Shortening a run by lowering its *rate* would make it a different experiment
    wearing the same name.
    """
    if arguments.scale == 1.0:
        return PHASES
    return tuple(
        Phase(
            name=phase.name,
            seconds=max(2.0, phase.seconds * arguments.scale),
            rate_per_second=phase.rate_per_second,
            note=phase.note,
        )
        for phase in PHASES
    )


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", default=str(HERE / "fixture.json"))
    parser.add_argument(
        "--api-pid",
        type=int,
        default=None,
        help="The uvicorn process to sample CPU and memory from",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="A Postgres DSN, to sample connection saturation. Opt-in on purpose.",
    )
    parser.add_argument(
        "--connections",
        type=int,
        default=200,
        help=(
            "Sockets the driver may hold open. Above the offered rate times the "
            "slowest workload, or the driver queues and measures itself."
        ),
    )
    parser.add_argument(
        "--scale",
        type=float,
        default=1.0,
        help="Multiply every phase's duration. 0.1 is a smoke run at the same rates.",
    )
    parser.add_argument("--title", default="AgenticOS load and resilience run")
    parser.add_argument(
        "--topology",
        default="one API worker, Postgres and Redis in containers, the stub model local",
        help="What was running, in one line. It goes at the top of the report.",
    )
    return parser.parse_args(argv)


def main() -> None:
    arguments = parse()
    if not Path(arguments.fixture).exists():
        raise SystemExit(f"No fixture at {arguments.fixture}. Run seed.py first.")
    print(asyncio.run(measure(arguments)))


if __name__ == "__main__":
    main()
