"""Public OpenAI raw-response shape used by isolated embedding adapter tests."""

import json
from unittest.mock import MagicMock


def embedding_response(vectors: list[object], *, prompt_tokens: int | None = None) -> MagicMock:
    payload: dict[str, object] = {"data": [{"embedding": vector} for vector in vectors]}
    if prompt_tokens is not None:
        payload["usage"] = {"prompt_tokens": prompt_tokens}
    return MagicMock(http_response=MagicMock(content=json.dumps(payload).encode()))
