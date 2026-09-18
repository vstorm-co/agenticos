"""Which ML services this deployment serves, and what the rest still need.

FA-069 asks for the Lot 3 ML services to be reachable as standalone API
services rather than only from inside an agent turn, and its acceptance asks
first for a *coverage matrix*: every mandatory service family mapped to an
endpoint, with the remaining dependencies named rather than implied. This
module is that matrix, as data - `GET /api/v1/ml/services` serves it and
`docs/ml-services.md` prints it, so an integrator and a reviewer read one list.

**A row is a claim, so the vocabulary is narrow on purpose.** `served` means
this deployment answers the named endpoint with the named engine. `dependency`
means the family is required and something is missing, and the row says what.
`prepared` is B01's own "architecture prep only": nothing ships, and the seam
that would carry it is named. The issue asks explicitly that an internal parser
or a proxy to an engine nobody provides is not presented as a delivered
service, which is why the engine is a field: a reader can see what is actually
doing the work before believing the state beside it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class DeliveryState(StrEnum):
    """How far one service family has been delivered on this deployment."""

    SERVED = "served"
    DEPENDENCY = "dependency"
    PREPARED = "prepared"


@dataclass(frozen=True)
class MLServiceEntry:
    """One row of the coverage matrix."""

    id: str
    family: str
    requirements: tuple[str, ...]
    endpoint: str | None
    """The REST path that answers, or None where nothing does yet."""

    engine: str
    """What actually performs the work, named so the state can be checked."""

    state: DeliveryState
    note: str
    """What a caller gets, or - for anything short of `served` - what is missing."""


SERVICE_CATALOG: tuple[MLServiceEntry, ...] = (
    MLServiceEntry(
        id="document_analysis",
        family="Document processing and understanding",
        requirements=("FA-069", "FA-070"),
        endpoint="POST /api/v1/ml/documents/analyze",
        engine="LiteParse (PDFium, layout-aware) or PyMuPDF, in this deployment",
        state=DeliveryState.SERVED,
        note=(
            "Returns the document's pages as markdown with the layout preserved, plus the "
            "prepared chunks and the file's metadata. Runs locally; nothing leaves the host."
        ),
    ),
    MLServiceEntry(
        id="ocr",
        family="Document processing and understanding",
        requirements=("FA-069", "FA-071"),
        endpoint="POST /api/v1/ml/documents/ocr",
        engine="LiteParse OCR: bundled Tesseract, or an OCR server registered as a local service",
        state=DeliveryState.SERVED,
        note=(
            "Recognises text on every page rather than only where the text layer is thin, "
            "so a scan and a born-digital page answer the same way. The language is the "
            "caller's; the engine is on the deployment's own network either way."
        ),
    ),
    MLServiceEntry(
        id="speech_to_text",
        family="Audio",
        requirements=("FA-069", "FA-072"),
        endpoint="POST /api/v1/ml/audio/transcriptions",
        engine="The organization's own transcription provider, over OpenAI's transcriptions API",
        state=DeliveryState.SERVED,
        note=(
            "The engine is whichever endpoint the organization's model profile names, which "
            "is a vendor or a self-hosted server speaking the same API - a deployment that "
            "may send no audio to a vendor points the profile at its own host and the "
            "endpoint is unchanged. No engine is assumed to exist that the operator has not "
            "configured: an organization with no transcription credential is refused, saying so."
        ),
    ),
    MLServiceEntry(
        id="pii_detection",
        family="Privacy",
        requirements=("FA-069", "FA-073"),
        endpoint="POST /api/v1/ml/privacy/pii",
        engine="The pattern detectors in pydantic-ai-harness, as the guardrails capability uses them",
        state=DeliveryState.SERVED,
        note=(
            "Counts what was found per category and returns the text with each match "
            "replaced. Covers email addresses, IBANs, payment card numbers and US social "
            "security numbers, each shape-matched and then checked - Luhn for a card, "
            "ISO 7064 for an IBAN - so a run of digits is not reported as an account."
        ),
    ),
    MLServiceEntry(
        id="pii_named_entities",
        family="Privacy",
        requirements=("FA-073", "DA-007"),
        endpoint=None,
        engine="None on this deployment",
        state=DeliveryState.DEPENDENCY,
        note=(
            "Personal names, postal addresses and telephone numbers are not pattern-shaped "
            "and are not detected. They need a named-entity model per language in scope, "
            "which is a model to select and host rather than a route to add - the detection "
            "endpoint above will carry the extra categories once one is provided."
        ),
    ),
    MLServiceEntry(
        id="image_analysis",
        family="Image",
        requirements=("FA-074",),
        endpoint=None,
        engine="None on this deployment",
        state=DeliveryState.PREPARED,
        note=(
            "Architecture preparation in B01 rather than initial rollout. Object detection "
            "and image classification ship no engine here; the seam is this catalog and the "
            "call record, which a new service joins without the callers changing."
        ),
    ),
)


def entry(service_id: str) -> MLServiceEntry | None:
    """The catalog row for one service id, or None where there is no such service."""
    return next((row for row in SERVICE_CATALOG if row.id == service_id), None)


def served_ids() -> tuple[str, ...]:
    """The ids an endpoint on this deployment actually answers."""
    return tuple(row.id for row in SERVICE_CATALOG if row.state is DeliveryState.SERVED)
