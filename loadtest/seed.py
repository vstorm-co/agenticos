"""The fixture a load run drives: an agent, a collection and a routine.

Built through the HTTP API rather than by writing rows, for the reason the whole
suite exists: a fixture assembled behind the product's own validation would let a
run measure a state the product cannot actually produce. Everything here is a
call a person could make from the console.

**Nothing in it costs money.** The agent runs on a model profile whose `base_url`
is the load stub, and the collection embeds through a `local_services` row whose
address is the same stub - which is what a keyless Ollama endpoint is, as far as
the platform is concerned. So a run touches no vendor, and a deployment with no
provider key at all can still be measured.

Idempotent by name: run it twice and it finds what it made the first time. That
matters more here than usual, because a load run is repeated and re-seeding
between runs would make retrieval times incomparable.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

WEBHOOK_SECRET = "loadtest-webhook-signing-key-not-a-credential"
"""What the fixture's webhook trigger is signed with.

A literal, and safe to be one: it is created by this script for a trigger this
script created, on a deployment somebody is load-testing. The deliveries it signs
carry nothing but a counter.
"""

EMBEDDING_MODEL = "nomic-embed-text"
EMBEDDING_DIM = 768
"""Ollama's smallest catalogued width, and what `stub_model.py` serves by
default. The two have to agree: a collection's table is created at its model's
width, and vectors of another length are refused by the store."""

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent / "backend"

COLLECTION = "loadtest"
AGENT_SLUG = "load-test-responder"
DOCUMENT_WORDS = 220


@dataclass(frozen=True)
class Fixture:
    """What a run needs in hand before it starts offering requests.

    **No credential is in here.** An earlier version wrote the seeding session's
    access token into the file, which put a live bearer token in clear text on
    disk for anyone who could read the directory - and made the fixture expire,
    so a run started an hour later refused with a message about re-seeding. The
    run signs in for itself instead, with a password it is given on the command
    line, and the webhook's signing secret is a constant in this module that the
    driver imports rather than a value carried through a file.
    """

    base_url: str
    organization_id: str
    agent_id: str
    collection: str
    trigger_id: str | None
    trigger_source: str | None

    def to_json(self) -> str:
        return json.dumps(
            {
                "base_url": self.base_url,
                "organization_id": self.organization_id,
                "agent_id": self.agent_id,
                "collection": self.collection,
                "trigger_id": self.trigger_id,
                "trigger_source": self.trigger_source,
            },
            indent=2,
        )

    @classmethod
    def from_json(cls, raw: str) -> Fixture:
        return cls(**json.loads(raw))


class Console:
    """A thin client over the API, raising with the body when it refuses.

    The body matters: this API's refusals name the field, and a seeding script
    that printed `400 Bad Request` and nothing else would send whoever runs it to
    read the server log for a sentence that was already in the response.
    """

    def __init__(self, client: httpx.Client, organization_id: str | None = None) -> None:
        self.client = client
        self.organization_id = organization_id

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        headers = dict(kwargs.pop("headers", {}))
        if self.organization_id:
            headers["X-Organization-Id"] = self.organization_id
        response = self.client.request(method, path, headers=headers, **kwargs)
        if response.status_code >= 400:
            raise RuntimeError(f"{method} {path} -> {response.status_code} {response.text[:400]}")
        return response.json() if response.content else None

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Any:
        return self.request("POST", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> Any:
        return self.request("DELETE", path, **kwargs)


def sign_in(base_url: str, email: str, password: str) -> tuple[httpx.Client, str]:
    """A client carrying an access token, and the organization to act in."""
    client = httpx.Client(base_url=f"{base_url}/api/v1", timeout=60.0)
    token = client.post("/auth/login", data={"username": email, "password": password})
    if token.status_code >= 400:
        raise RuntimeError(f"Could not sign in as {email}: {token.text[:200]}")
    access = token.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {access}"
    memberships = client.get("/orgs").json().get("items") or []
    if not memberships:
        raise RuntimeError(f"{email} belongs to no organization; run `agenticos cmd bootstrap`.")
    return client, memberships[0]["id"]


def stub_secret(console: Console) -> str:
    """A vault entry holding the key the stub ignores.

    The stub authenticates nothing, and the profile still needs a secret: what a
    run is attributed to is the binding between a model and a key, and seeding a
    profile without one would exercise a path the product does not have.
    """
    existing = console.get("/secrets")
    for row in existing.get("items", existing if isinstance(existing, list) else []):
        if row.get("name") == "loadtest-stub":
            return str(row["id"])
    created = console.post(
        "/secrets",
        json={
            "name": "loadtest-stub",
            "description": "Not a credential. The load stub accepts anything.",
            "value": {"kind": "api_key", "api_key": "stub-key-not-a-secret"},
            "purpose": "openai",
            "visibility": "org",
        },
    )
    return str(created["id"])


def model_profile(console: Console, *, secret_id: str, stub_url: str) -> str:
    """The profile the load agent runs on, pointed at the stub."""
    for row in console.get("/providers/model-profiles").get("items", []):
        if row.get("label") == "Load stub":
            return str(row["id"])
    created = console.post(
        "/providers/model-profiles",
        json={
            "label": "Load stub",
            "provider": "openai",
            "model": "stub-chat",
            "secret_id": secret_id,
            "base_url": f"{stub_url}/v1",
        },
    )
    return str(created["id"])


def embedding_endpoint(console: Console, *, stub_url: str) -> str:
    """A local service standing in for an Ollama server, which is the stub."""
    for row in console.get("/local-services").get("items", []):
        if row.get("name") == "Load stub embeddings":
            return str(row["id"])
    created = console.post(
        "/local-services",
        json={
            "name": "Load stub embeddings",
            "kind": "embedding",
            "provider": "ollama",
            "base_url": f"{stub_url}/v1",
        },
    )
    return str(created["id"])


def agent(console: Console, *, profile_id: str) -> str:
    """A published agent that answers on the stub, with no tools bound.

    No capabilities on purpose. What the chat and run workloads measure is the
    platform's own path to a model - the socket, the spec, the budget check, the
    rows - and a tool call would put the stub's latency in the middle of it twice.
    """
    for row in console.get("/agents", params={"limit": 100}).get("items", []):
        if row.get("slug") == AGENT_SLUG:
            agent_id = str(row["id"])
            break
    else:
        created = console.post(
            "/agents",
            json={
                "spec": {
                    "name": "Load test responder",
                    "instructions": (
                        "Answer in one short sentence. You exist to be measured, "
                        "not to be interesting."
                    ),
                    "model_profile_id": profile_id,
                }
            },
        )
        agent_id = str(created["id"])
    console.post(f"/agents/{agent_id}/publish", json={"note": "load test fixture"})
    return agent_id


def collection(console: Console, *, endpoint_id: str) -> str:
    """The knowledge base retrieval is measured against."""
    for row in console.get("/kb").get("items", []):
        if row.get("collection_name") == COLLECTION:
            return COLLECTION
    console.post(
        "/kb",
        json={
            "name": "Load test corpus",
            "scope": "org",
            "collection_name": COLLECTION,
            "embedding_provider": "ollama",
            "embedding_model": EMBEDDING_MODEL,
            "embedding_endpoint_id": endpoint_id,
        },
    )
    return COLLECTION


def document(index: int) -> bytes:
    """One synthetic document, long enough to chunk and stable across runs.

    Generated rather than shipped: a corpus in the repository is a corpus that
    has to be licensed, reviewed and translated, and what retrieval time depends
    on is how many chunks there are, not what they say.
    """
    sentences = [
        f"Document {index} describes procedure {index * 7 % 97} of the municipal service catalogue.",
        "Applications are received, checked for completeness and passed to the responsible office.",
        f"Reference {index:05d} identifies this record in the register for the current period.",
    ]
    words: list[str] = []
    while len(words) < DOCUMENT_WORDS:
        words.extend(sentences[len(words) % len(sentences)].split())
    return " ".join(words).encode()


def corpus(directory: Path, count: int) -> Path:
    """Write the synthetic corpus to disk for the ingestion command to read."""
    directory.mkdir(parents=True, exist_ok=True)
    for index in range(count):
        (directory / f"record-{index:05d}.txt").write_bytes(document(index))
    return directory


def ingest(*, name: str, count: int) -> int:
    """Index `count` documents into the collection, in this process.

    Through `agenticos cmd rag-ingest` rather than through the upload endpoint,
    and the difference is the whole reason this note exists. An upload answers
    202 and hands the parse and the embedding to a Prefect flow, so seeding that
    way needs the worker stack up and finishes whenever it finishes. The command
    does the same work synchronously and reports when the corpus is actually
    searchable, which is what a run has to know before it starts timing
    retrieval.

    It is not a shortcut around the product: the same parser, the same splitter,
    the same embedding client and the same store. What it skips is the queue,
    which the `ingest` workload measures on its own terms.
    """
    directory = corpus(HERE / "corpus", count)
    result = subprocess.run(  # noqa: S603 - a literal argv, no shell
        [
            sys.executable,
            "-m",
            "cli.commands",
            "cmd",
            "rag-ingest",
            str(directory),
            "--collection",
            name,
            "--recursive",
            "--sync-mode",
            "new_only",
        ],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"rag-ingest failed:\n{result.stdout[-1500:]}\n{result.stderr[-1500:]}")
    return count


def trigger(console: Console, *, agent_id: str) -> tuple[str | None, str | None]:
    """A webhook routine the run fires, or (None, None) where none can be made.

    Not fatal when it cannot be created: the trigger workload is three per cent
    of the mix, and a run that measured everything else is worth more than a run
    that refused to start. The report says the scenario was skipped rather than
    reporting zero failures for it.
    """
    try:
        existing = console.get(f"/agents/{agent_id}/triggers").get("items", [])
        for row in existing:
            if row.get("name") == "Load test webhook":
                # Recreated rather than reused. The signing secret is write-only -
                # `TriggerUpdate` cannot change it and rotation mints a random one -
                # so a trigger left over from an earlier fixture would keep a secret
                # this run does not know, and every delivery would be a 403 that
                # looked like a platform failure.
                console.delete(f"/agents/{agent_id}/triggers/{row['id']}")
        created = console.post(
            f"/agents/{agent_id}/triggers",
            json={
                "name": "Load test webhook",
                "prompt": "Summarise the event in one line.",
                "trigger_type": "event",
                "event_source": "webhook",
                "event_secret": WEBHOOK_SECRET,
            },
        )
        return str(created["id"]), str(created.get("event_source") or "webhook")
    except RuntimeError as failure:
        print(f"  trigger skipped: {failure}", file=sys.stderr)
        return None, None


def build(*, base_url: str, stub_url: str, email: str, password: str, documents: int) -> Fixture:
    """Make everything a run needs, and hand back what it has to know."""
    client, organization_id = sign_in(base_url, email, password)
    console = Console(client, organization_id)
    secret_id = stub_secret(console)
    profile_id = model_profile(console, secret_id=secret_id, stub_url=stub_url)
    endpoint_id = embedding_endpoint(console, stub_url=stub_url)
    agent_id = agent(console, profile_id=profile_id)
    name = collection(console, endpoint_id=endpoint_id)
    added = ingest(name=name, count=documents)
    trigger_id, trigger_source = trigger(console, agent_id=agent_id)
    print(f"  organization {organization_id}")
    print(f"  agent        {agent_id}")
    print(f"  collection   {name} ({added} documents indexed)")
    print(f"  trigger      {trigger_id or 'skipped'}")
    return Fixture(
        base_url=base_url,
        organization_id=organization_id,
        agent_id=agent_id,
        collection=name,
        trigger_id=trigger_id,
        trigger_source=trigger_source,
    )


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--stub-url", default="http://127.0.0.1:4020")
    parser.add_argument("--email", default="admin@example.com")
    parser.add_argument("--password", default="admin123")
    parser.add_argument("--documents", type=int, default=40)
    parser.add_argument(
        "--out",
        default=str(HERE / "fixture.json"),
        help=(
            "Where the fixture is written. It carries a live access token, so it "
            "sits beside this script and is ignored by git."
        ),
    )
    return parser.parse_args(argv)


def main() -> None:
    arguments = parse()
    fixture = build(
        base_url=arguments.base_url,
        stub_url=arguments.stub_url,
        email=arguments.email,
        password=arguments.password,
        documents=arguments.documents,
    )
    Path(arguments.out).write_text(fixture.to_json(), encoding="utf-8")
    print(f"  written to   {arguments.out}")


if __name__ == "__main__":
    main()
