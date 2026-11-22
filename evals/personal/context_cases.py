"""Validate and export richer context fixtures in the platform's existing dataset format.

These cases describe the desired broader assistance contract. They do not silently
change the older nightly schema or its 50-case score. Real-user packets stay outside
this repository; only synthetic fixtures are committed.
"""

import argparse
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "backend"
if BACKEND.is_dir():
    sys.path.insert(0, str(BACKEND))

from app.schemas.dataset import DatasetCaseContent
from app.schemas.personal_context import ContextPacket
from app.services.dataset_files import parse

DATASET = Path(__file__).with_name("datasets") / "context.jsonl"


def load_context_cases(path: Path = DATASET) -> list[DatasetCaseContent]:
    """Use the production importer, then verify the context/partition contracts."""
    cases = parse(path.read_bytes(), "jsonl")
    identifiers: set[str] = set()
    for case in cases:
        packet = ContextPacket.model_validate_json(case.input)
        source_ids = [message.id for message in packet.messages]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("A context packet has duplicate source message IDs")
        ids = [tag.removeprefix("case:") for tag in case.tags if tag.startswith("case:")]
        if len(ids) != 1 or not ids[0] or ids[0] in identifiers:
            raise ValueError("Context cases require one unique case ID")
        identifiers.add(ids[0])
        if len(set(case.tags) & {"train", "holdout"}) != 1:
            raise ValueError("Context cases require exactly one evaluation partition")
        if len(set(case.tags) & {"memory", "proactivity"}) != 1:
            raise ValueError("Context cases require exactly one target component")
        if case.reference_answer is None or case.counter_example is None:
            raise ValueError("Context cases require expected and counter-example behavior")
    return cases


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--export", type=Path, help="Write importable JSONL; never calls a model")
    args = parser.parse_args()
    cases = load_context_cases(args.dataset)
    if args.export is not None:
        args.export.write_text("".join(case.model_dump_json() + "\n" for case in cases))
    print(
        json.dumps(
            {
                "context_cases": len(cases),
                "memory": sum("memory" in case.tags for case in cases),
                "proactivity": sum("proactivity" in case.tags for case in cases),
                "holdout": sum("holdout" in case.tags for case in cases),
            }
        )
    )


if __name__ == "__main__":
    main()
