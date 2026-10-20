"""What the authoring rows say about themselves in a log line."""

import uuid

from app.db.models.authoring import AuthoringRequest, SpecProposalBatch, SpecProposalHunk


def test_each_row_names_itself_by_id_and_state():
    request = AuthoringRequest(id=uuid.uuid4(), kind="improve", target="agent", status="queued")
    batch = SpecProposalBatch(id=uuid.uuid4(), agent_id=uuid.uuid4(), status="open")
    hunk = SpecProposalHunk(id=uuid.uuid4(), kind="instructions", status="pending")

    assert "improve" in repr(request) and "queued" in repr(request)
    assert str(batch.agent_id) in repr(batch) and "open" in repr(batch)
    assert "instructions" in repr(hunk) and "pending" in repr(hunk)
