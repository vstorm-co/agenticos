"""No secret leaves the API. Asserted over the whole surface, not route by route.

A secret escapes through the schema somebody added last, which is exactly the
route no hand-written test names. So this sweeps the generated OpenAPI document
instead: every response schema of every route, with `$ref` chains resolved,
checked against the shapes and the field names a plaintext could travel in.

Two checks, because they fail differently. The *model* check catches a
`SecretRead` that grew a `value` field by echoing back what it was sent -
the payload models are reachable from request bodies on purpose and from
responses never. The *field* check catches a new schema that spells a secret out
by hand without going through those models at all.

Adding a route that returns a credential should fail here. If it does, the fix
is the route, not the allowlist.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from app.main import app

# The payload models a stored secret is made of. Reachable from a request body,
# never from a response.
_SECRET_MODELS = frozenset(
    {
        "ApiKeySecret",
        "AzureOpenAISecret",
        "AwsCredentialsSecret",
        "GcpServiceAccountSecret",
        # `NoSecret` is deliberately absent. It said "this provider needs no
        # key", and the only thing that ever accepted it was the credential
        # store that the vault replaced - the vault has no such shape, because a
        # secret with no value is not a secret. A self-hosted endpoint that
        # authenticates nothing has no way to be configured right now; see
        # `model_catalog` and `ProviderSpec.keyless`.
    }
)

# Field names that would be a plaintext credential if they appeared in a
# response body. `access_token` and `refresh_token` are deliberately absent:
# they are this API's *own* session tokens, and issuing them is what
# /auth/login is for.
_SECRET_FIELDS = frozenset(
    {
        "api_key",
        "auth_token",
        "aws_secret_access_key",
        "aws_session_token",
        "client_secret",
        "oauth_payload",
        "oauth_pending_payload",
        "password",
        "sealed_secret",
        "secret",
        "service_account_json",
        "token_encrypted",
    }
)

# Names on the list above are the ones somebody thought of. This pattern
# catches the ones nobody did - any string-ish field whose name says "secret".
# It is the half that found `InvitationRead.token`, which is not on the list
# above and never would have been: nothing about the name `token` is unusual
# until you notice the response hands out a bearer credential.
_SECRET_WORDS = re.compile("secret|password|token|api_key|private_key")

# Fields the pattern matches that are nonetheless safe. Every entry is a
# promise about the value, and writing the promise down is the point - an
# allowance nobody can explain is a hole.
_PATTERN_ALLOWED: dict[str, str] = {
    "has_auth_token": "a boolean saying whether one is set",
    "token_hint": "the last four characters, so two keys can be told apart",
    "access_token": "minted for the caller who just authenticated - it is theirs",
    "refresh_token": "same: issued to this caller, not read from storage",
    "token_type": "the string 'bearer'",
    "expires_in": "a lifetime in seconds",
    "share_token": (
        "returned so the creator can build the link they just asked for; "
        "the caller and the subject are the same person"
    ),
    # `InvitationRead.token` used to be here as a known leak: listing an
    # organization's invitations returned every pending bearer credential. It
    # was found by this rule and is now fixed - creation returns
    # `invitation_token` once, listing returns none - so the allowance is gone
    # rather than kept "just in case". That round trip is what the rule is for.
    "invitation_token": "the inviter's own copy of the link, returned once at creation",
    "secret_id": "a reference to a stored secret, not the secret",
    "llamaparse_secret_id": (
        "a collection's pointer at the vault key its parses are billed to - an id, never the key"
    ),
    "logfire_token_secret_id": (
        "an environment's pointer at a vault-held write token - the id names "
        "which key, never the key"
    ),
    "embedding_secret_id": (
        "the same again: which vault key a collection embeds on - the id of a "
        "reference the organization can revoke, never the key itself"
    ),
    "token_secret_id": (
        "the same, named for what it points at: an agent's Logfire write token "
        "lives in the vault and the spec carries only its id, because a spec is "
        "exported as YAML into somebody's repository"
    ),
    "secret_kind": "which shape a secret has to be, e.g. 'api_key'",
    "requires_secret": "what kind a capability needs, so the Builder can ask for one",
    "tokens_used": "an LLM usage count - 'token' means something else here",
    "input_tokens": "the same count, split: prompt tokens billed for one turn",
    "output_tokens": "the same, for the completion",
    "context_used_tokens": "the same word again: how much of a context window a turn filled",
    "context_window_tokens": "how many tokens a model accepts, which is a capacity not a key",
}

# A property whose type is one of these cannot be carrying a credential
# whatever it is called - `ConnectorConfigField.secret` is a flag saying "this
# input should be masked", which is the opposite of a leak.
_HARMLESS_TYPES = frozenset({"boolean", "integer", "number"})


@pytest.fixture(scope="module")
def document() -> dict[str, Any]:
    return app.openapi()


def _referenced(node: Any) -> set[str]:
    """Every component name a schema fragment points at, one level deep."""
    names: set[str] = set()
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            names.add(ref.rsplit("/", 1)[-1])
        for value in node.values():
            names |= _referenced(value)
    elif isinstance(node, list):
        for item in node:
            names |= _referenced(item)
    return names


def _response_schema_names(document: dict[str, Any]) -> set[str]:
    """Every component reachable from any response body, transitively."""
    components: dict[str, Any] = document.get("components", {}).get("schemas", {})
    frontier: set[str] = set()
    for methods in document["paths"].values():
        for operation in methods.values():
            if not isinstance(operation, dict):
                continue
            frontier |= _referenced(operation.get("responses", {}))

    seen: set[str] = set()
    while frontier:
        name = frontier.pop()
        if name in seen:
            continue
        seen.add(name)
        frontier |= _referenced(components.get(name, {})) - seen
    return seen


def _properties(schema: dict[str, Any]) -> set[str]:
    properties = schema.get("properties")
    return set(properties) if isinstance(properties, dict) else set()


def _string_properties(schema: dict[str, Any]) -> set[str]:
    """Property names that could hold a credential - anything not plainly scalar."""
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return set()
    return {
        name
        for name, definition in properties.items()
        if not (isinstance(definition, dict) and definition.get("type") in _HARMLESS_TYPES)
    }


class TestNoSecretShapeIsReturned:
    def test_no_response_can_carry_a_secret_payload(self, document: dict[str, Any]) -> None:
        """There is no endpoint that returns a plaintext, by construction.

        Reading a secret is the runtime's privilege: the agent runner unseals
        one and injects it into the capability that declared it. A client that
        needs to tell two secrets apart gets the name and four characters.
        """
        reachable = _response_schema_names(document)
        # FastAPI suffixes a model whose input and output schemas differ.
        leaked = sorted(
            name
            for name in reachable
            if name.removesuffix("-Input").removesuffix("-Output") in _SECRET_MODELS
        )
        assert not leaked, f"secret payloads reachable from a response: {leaked}"

    def test_the_secret_payloads_are_still_accepted_on_the_way_in(
        self, document: dict[str, Any]
    ) -> None:
        """The other half: a test that passed because the models vanished would be worthless."""
        components = document.get("components", {}).get("schemas", {})
        present = {name.removesuffix("-Input").removesuffix("-Output") for name in components}
        assert present >= _SECRET_MODELS

    def test_no_response_field_is_named_like_a_credential(self, document: dict[str, Any]) -> None:
        components: dict[str, Any] = document.get("components", {}).get("schemas", {})
        offenders = sorted(
            f"{name}.{field}"
            for name in _response_schema_names(document)
            for field in _string_properties(components.get(name, {})) & _SECRET_FIELDS
        )
        assert not offenders, f"response schemas exposing a credential field: {offenders}"

    def test_no_response_field_reads_like_a_credential(self, document: dict[str, Any]) -> None:
        """The pattern half, for the names nobody listed.

        A named list only ever contains what somebody anticipated. This is what
        catches the field added next month, at the moment its schema is written
        rather than the moment somebody thinks to test it.
        """
        components: dict[str, Any] = document.get("components", {}).get("schemas", {})
        offenders = sorted(
            f"{name}.{field}"
            for name in _response_schema_names(document)
            for field in _string_properties(components.get(name, {}))
            if _SECRET_WORDS.search(field) and field not in _PATTERN_ALLOWED
        )
        assert not offenders, f"response schemas exposing a credential field: {offenders}"

    def test_every_allowance_still_names_a_real_field(self, document: dict[str, Any]) -> None:
        """A stale allowance is a hole waiting for the name to be reused."""
        components: dict[str, Any] = document.get("components", {}).get("schemas", {})
        named = {field for schema in components.values() for field in _properties(schema)}

        assert set(_PATTERN_ALLOWED) <= named

    def test_the_sweep_reaches_the_schemas_it_claims_to(self, document: dict[str, Any]) -> None:
        """A sweep that resolves nothing passes for the wrong reason.

        This is the failure the file exists to prevent, turned on itself: if
        `$ref` resolution broke, every assertion above would go quietly green.
        """
        reachable = _response_schema_names(document)

        assert len(reachable) > 50
        assert "SecretRead" in reachable


class TestWhatIsReturnedInstead:
    @pytest.mark.parametrize("schema_name", ["SecretRead"])
    def test_a_stored_credential_is_identified_by_a_hint(
        self, document: dict[str, Any], schema_name: str
    ) -> None:
        """Four characters name a key to its owner and are useless to anyone else."""
        schema = document["components"]["schemas"][schema_name]
        assert "hint" in _properties(schema)

    def test_a_bot_token_never_appears_in_its_read_schema(self, document: dict[str, Any]) -> None:
        """The channel bot's token is now a vault envelope; it was never returned
        and must not start being returned because the column was renamed."""
        schema = document["components"]["schemas"]["ChannelBotRead"]
        assert not _properties(schema) & _SECRET_FIELDS
