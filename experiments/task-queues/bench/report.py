"""Turn `results/` into the tables of the report.

    python -m bench.report results > results/TABLES.md

Every number comes from the events the tasks wrote (one clock) and the samples the
driver took. Percentiles are over jobs; resource figures over the seconds between
the first submission and the last job finishing.
"""

import csv
import glob
import json
import os
import statistics
import sys
from collections import defaultdict
from typing import Any

WORKER_PREFIX = "w-"
INFRA = ("postgres", "redis", "prefect-server", "hatchet")


def pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = (len(ordered) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def fmt(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "-"
    return f"{value:.{digits}f}"


def load_jobs(path: str) -> dict[str, dict[str, Any]]:
    jobs: dict[str, dict[str, Any]] = {}
    with open(path) as handle:
        for row in csv.DictReader(handle):
            job = jobs.setdefault(
                row["job_id"],
                {
                    "kind": row["kind"],
                    "tenant": row["tenant"],
                    "chain": row["chain_id"],
                    "step": int(row["step"]) if row["step"] not in ("", "None") else None,
                    "enq": float(row["enqueued_at"]),
                    "starts": [],
                    "finishes": [],
                },
            )
            if row["event"] == "started":
                job["starts"].append(float(row["at"]))
            elif row["event"] == "finished":
                job["finishes"].append(float(row["at"]))
    return jobs


def resources(result: dict[str, Any], start: float, end: float) -> dict[str, Any]:
    by_container: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sample in result["samples"]:
        if start <= sample["t"] <= end:
            by_container[sample["container"]].append(sample)

    def role(name: str) -> str:
        service = name.split("-", 1)[1].rsplit("-", 1)[0] if "-" in name else name
        if service.startswith(WORKER_PREFIX):
            return "workers"
        return service if service in INFRA else "other"

    roles: dict[str, dict[str, float]] = defaultdict(lambda: {"cpu_avg": 0.0, "cpu_p95": 0.0, "mem_max": 0.0})
    for name, samples in by_container.items():
        r = roles[role(name)]
        cpu = [s["cpu"] for s in samples]
        r["cpu_avg"] += statistics.fmean(cpu)
        r["cpu_p95"] += pct(cpu, 95) or 0
        r["mem_max"] += max(s["mem_mb"] for s in samples)
    total = {
        "cpu_avg": sum(r["cpu_avg"] for r in roles.values()),
        "mem_max": sum(r["mem_max"] for r in roles.values()),
    }
    return {"roles": dict(roles), "total": total}


def summarize(json_path: str) -> dict[str, Any]:
    result = json.load(open(json_path))
    jobs = load_jobs(json_path.replace(".json", ".events.csv"))
    work = {k: j for k, j in jobs.items() if j["kind"] != "sweep"}
    finished = [j for j in work.values() if j["finishes"]]
    first_enq = min((j["enq"] for j in work.values()), default=result["started_at"])
    last_finish = max((min(j["finishes"]) for j in finished), default=result["ended_at"])
    waits = [min(j["starts"]) - j["enq"] for j in work.values() if j["starts"]]
    e2e = [min(j["finishes"]) - j["enq"] for j in finished]
    summary: dict[str, Any] = {
        "label": result["label"],
        "variant": result["variant"] or result["backend"],
        "scenario": result["scenario"],
        "expected": result["expected_jobs"],
        "finished": len(finished),
        "lost": result["expected_jobs"] - len(finished),
        "duplicated": sum(1 for j in finished if len(j["finishes"]) > 1),
        "re_executed": sum(1 for j in work.values() if len(j["starts"]) > 1),
        "makespan_s": last_finish - first_enq,
        "throughput_per_s": len(finished) / max(0.001, last_finish - first_enq),
        "wait_p50": pct(waits, 50),
        "wait_p95": pct(waits, 95),
        "wait_p99": pct(waits, 99),
        "e2e_p50": pct(e2e, 50),
        "e2e_p95": pct(e2e, 95),
        "pg": result["pg"],
        "resources": resources(result, first_enq, last_finish),
    }
    if result["scenario"] == "probe" and finished and result.get("workers_started_at"):
        summary["cold_start_s"] = min(finished[0]["finishes"]) - result["workers_started_at"]
    if result["scenario"] == "workflow":
        chains: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for j in work.values():
            chains[j["chain"]].append(j)
        totals, hops = [], []
        for steps in chains.values():
            steps.sort(key=lambda j: j["step"])
            if all(s["finishes"] for s in steps):
                totals.append(min(steps[-1]["finishes"]) - steps[0]["enq"])
            for a, b in zip(steps, steps[1:]):
                if a["finishes"] and b["starts"]:
                    hops.append(min(b["starts"]) - min(a["finishes"]))
        summary.update(
            chain_p50=pct(totals, 50), chain_p95=pct(totals, 95), hop_p50=pct(hops, 50), hop_p95=pct(hops, 95)
        )
    if result["scenario"] == "mix":
        for kind in ("agent", "parse"):
            kw = [min(j["starts"]) - j["enq"] for j in work.values() if j["kind"] == kind and j["starts"]]
            summary[f"{kind}_wait_p50"] = pct(kw, 50)
            summary[f"{kind}_wait_p95"] = pct(kw, 95)
            summary[f"{kind}_wait_p99"] = pct(kw, 99)
        ticks = sorted(min(j["starts"]) for j in jobs.values() if j["kind"] == "sweep" and j["starts"])
        gaps = [b - a for a, b in zip(ticks, ticks[1:])]
        summary["sweeps"] = len(ticks)
        summary["sweep_gap_mean"] = statistics.fmean(gaps) if gaps else None
        summary["sweep_gap_max_dev"] = max((abs(g - 60) for g in gaps), default=None)
    if result["scenario"] == "tenants":
        small = [min(j["starts"]) - j["enq"] for j in work.values() if j["tenant"] == "org-small" and j["starts"]]
        summary["small_wait_p50"] = pct(small, 50)
        summary["small_wait_p95"] = pct(small, 95)
        summary["small_wait_max"] = max(small) if small else None
        ends = sorted(min(j["finishes"]) for j in finished)
        summary["longest_stall_s"] = max((b - a for a, b in zip(ends, ends[1:])), default=None)
    return summary


def main(directory: str) -> None:
    summaries = []
    for path in sorted(glob.glob(os.path.join(directory, "*.json"))):
        if path.endswith("summary.json"):
            continue
        try:
            summaries.append(summarize(path))
        except Exception as exc:
            print(f"<!-- skipped {os.path.basename(path)}: {exc} -->", file=sys.stderr)
    json.dump(summaries, open(os.path.join(directory, "summary.json"), "w"), indent=1)

    def table(scenario: str, columns: list[tuple[str, str, int]]) -> None:
        rows = [s for s in summaries if s["scenario"] == scenario]
        if not rows:
            return
        print(f"\n### {scenario}\n")
        print("| variant | " + " | ".join(c[1] for c in columns) + " |")
        print("|---|" + "---|" * len(columns))
        for s in sorted(rows, key=lambda s: s["variant"]):
            cells = []
            for key, _, digits in columns:
                value = s
                for part in key.split("."):
                    value = value.get(part) if isinstance(value, dict) else None
                cells.append(fmt(value, digits) if isinstance(value, (int, float)) or value is None else str(value))
            print(f"| {s['variant']} | " + " | ".join(cells) + " |")

    common_res = [
        ("resources.roles.workers.cpu_avg", "workers CPU avg %", 0),
        ("resources.roles.workers.mem_max", "workers RAM max MB", 0),
        ("resources.total.cpu_avg", "stack CPU avg %", 0),
        ("resources.total.mem_max", "stack RAM max MB", 0),
        ("pg.commits", "PG commits", 0),
        ("pg.wal_bytes", "WAL bytes", 0),
    ]
    table("probe", [("cold_start_s", "cold start s", 1)])
    table(
        "workflow",
        [
            ("finished", "steps done", 0),
            ("lost", "lost", 0),
            ("hop_p50", "hop p50 s", 2),
            ("hop_p95", "hop p95 s", 2),
            ("chain_p50", "run p50 s", 1),
            ("chain_p95", "run p95 s", 1),
            ("makespan_s", "makespan s", 1),
            ("throughput_per_s", "steps/s", 1),
        ]
        + common_res,
    )
    table(
        "mix",
        [
            ("finished", "done", 0),
            ("lost", "lost", 0),
            ("agent_wait_p50", "agent wait p50", 2),
            ("agent_wait_p95", "agent wait p95", 2),
            ("parse_wait_p50", "parse wait p50", 2),
            ("parse_wait_p95", "parse wait p95", 2),
            ("sweeps", "sweeps", 0),
            ("sweep_gap_max_dev", "sweep max dev s", 1),
        ]
        + common_res,
    )
    table(
        "tenants",
        [
            ("finished", "done", 0),
            ("lost", "lost", 0),
            ("duplicated", "duplicated", 0),
            ("re_executed", "re-executed", 0),
            ("small_wait_p50", "small org wait p50", 2),
            ("small_wait_p95", "small org wait p95", 2),
            ("small_wait_max", "small org wait max", 1),
            ("longest_stall_s", "longest stall s", 1),
            ("makespan_s", "makespan s", 1),
        ]
        + common_res,
    )


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "results")
