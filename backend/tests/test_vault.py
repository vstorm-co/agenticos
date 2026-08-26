"""Tests for the secret vault.

The property that matters is the one a single global key cannot give: a sealed
secret is bound to the scope it was sealed for, so database access alone does
not let a row be moved between tenants - or between members - and read.
"""

import base64
import hashlib
import json
import uuid

import pytest
from cryptography.fernet import Fernet

from app.core.config import settings
from app.core.exceptions import BadRequestError, ConfigurationError
from app.core.vault import (
    ENVELOPE_VERSION,
    VaultScope,
    VaultScopeKind,
    current_key_version,
    generate_master_key,
    needs_rotation,
    rewrap,
    seal,
    seal_fields,
    unseal,
)

KEY_A = "vault-master-key-a-" + "a" * 32
KEY_B = "vault-master-key-b-" + "b" * 32
KEY_C = "vault-master-key-c-" + "c" * 32


def _org() -> VaultScope:
    return VaultScope.organization(uuid.uuid4())


@pytest.fixture
def three_master_keys(monkeypatch):
    """A deployment mid-rotation: three configured master keys, version 3 current."""
    keys = {1: KEY_A, 2: KEY_B, 3: KEY_C}
    monkeypatch.setattr(settings, "VAULT_MASTER_KEYS", keys)
    return keys


def _legacy_seal(plaintext: str, *, scope: VaultScope, key_version: int = 1) -> str:
    """An envelope the pre-HKDF vault would have written: version-1 format,
    wrapping key derived with a bare SHA-256 over the concatenated material."""
    master = (
        settings.VAULT_MASTER_KEYS.get(key_version)
        if settings.VAULT_MASTER_KEYS
        else (settings.VAULT_MASTER_KEY or settings.SECRET_KEY)
    )
    digest = hashlib.sha256(f"{master}|{scope}|v{key_version}".encode()).digest()
    wrapper = Fernet(base64.urlsafe_b64encode(digest))
    data_key = Fernet.generate_key()
    return json.dumps(
        {
            "v": 1,
            "k": wrapper.encrypt(data_key).decode(),
            "p": Fernet(data_key).encrypt(plaintext.encode()).decode(),
        },
        separators=(",", ":"),
    )


class TestSealFields:
    """Several fields of one row, sealed under one version.

    The shape hand-rolled at more than one model, each differently - one reset the
    version, one discarded it (#552). The helper is the one way to seal such a row,
    so those mistakes cannot be written by hand.
    """

    def test_every_field_is_sealed_at_the_returned_version_and_round_trips(self, three_master_keys):
        scope = _org()
        sealed, version = seal_fields(
            {"token": "sk-live-abcd", "secret": "signing-shhh"}, scope=scope, key_version=3
        )

        assert version == 3
        assert unseal(sealed["token"].ciphertext, scope=scope, key_version=3) == "sk-live-abcd"
        assert unseal(sealed["secret"].ciphertext, scope=scope, key_version=3) == "signing-shhh"

    def test_an_empty_field_is_skipped_rather_than_sealed(self):
        # A field the row does not carry is absent, not an envelope around nothing.
        sealed, _version = seal_fields({"token": "sk-live-abcd", "secret": ""}, scope=_org())

        assert set(sealed) == {"token"}

    def test_the_whole_row_can_be_rewrapped_together(self, three_master_keys):
        # One version per row is what lets a rotation move every field's wrapped
        # key in one pass and the row still open.
        scope = _org()
        sealed, _version = seal_fields({"a": "alpha", "b": "beta"}, scope=scope, key_version=1)

        moved = {
            name: rewrap(field.ciphertext, scope=scope, from_version=1, to_version=2)
            for name, field in sealed.items()
        }

        assert unseal(moved["a"], scope=scope, key_version=2) == "alpha"
        assert unseal(moved["b"], scope=scope, key_version=2) == "beta"


class TestSealUnseal:
    def test_roundtrip(self):
        scope = _org()
        sealed = seal("sk-live-abcd1234", scope=scope)
        assert unseal(sealed.ciphertext, scope=scope) == "sk-live-abcd1234"

    def test_hint_is_the_last_four_characters(self):
        sealed = seal("sk-live-abcd1234", scope=_org())
        assert sealed.hint == "1234"

    def test_ciphertext_never_contains_the_plaintext(self):
        secret = "sk-live-abcd1234"
        sealed = seal(secret, scope=_org())
        assert secret not in sealed.ciphertext

    def test_each_seal_is_distinct(self):
        """A fresh data key per secret - identical values must not look identical."""
        scope = _org()
        first = seal("same-secret", scope=scope)
        second = seal("same-secret", scope=scope)
        assert first.ciphertext != second.ciphertext

    def test_empty_secret_is_refused(self):
        """A credential that genuinely has no value is stored as no envelope at all.

        Sealing an empty string would produce a secret that says nothing and
        fails much later at the provider; the `none` kind is what "there is no
        credential" looks like.
        """
        with pytest.raises(BadRequestError):
            seal("", scope=_org())


class TestOwnerBinding:
    def test_another_organization_cannot_unseal(self):
        sealed = seal("sk-live-abcd1234", scope=_org())
        with pytest.raises(BadRequestError):
            unseal(sealed.ciphertext, scope=_org())

    def test_another_member_cannot_unseal(self):
        """Personal MCP credentials are bound to their owner, not to a tenant.

        A personal connection has no organization and its owner may belong to
        several, so the member is the only stable owner to bind to.
        """
        sealed = seal("ghp_personal", scope=VaultScope.user(uuid.uuid4()))
        with pytest.raises(BadRequestError):
            unseal(sealed.ciphertext, scope=VaultScope.user(uuid.uuid4()))

    def test_the_same_id_in_two_kinds_of_scope_are_different_owners(self):
        """The kind is part of the derivation, not decoration.

        Ids come from different tables and could collide; without the kind in
        the material, an organization envelope would open under a personal
        scope carrying the same uuid.
        """
        subject = uuid.uuid4()
        sealed = seal("secret", scope=VaultScope.organization(subject))
        with pytest.raises(BadRequestError):
            unseal(sealed.ciphertext, scope=VaultScope.user(subject))

    def test_wrong_key_version_cannot_unseal(self, three_master_keys):
        scope = _org()
        sealed = seal("sk-live-abcd1234", scope=scope, key_version=1)
        with pytest.raises(BadRequestError):
            unseal(sealed.ciphertext, scope=scope, key_version=2)

    def test_failure_message_does_not_say_which_part_was_wrong(self):
        """Distinguishing "wrong owner" from "wrong key" would help an attacker."""
        sealed = seal("secret", scope=_org())
        with pytest.raises(BadRequestError) as exc:
            unseal(sealed.ciphertext, scope=_org())
        assert "wrong master key or owner" in exc.value.message


class TestScopeIdentity:
    def test_a_scope_reads_as_kind_and_subject(self):
        """The string form is the key derivation input, so it has to be stable."""
        subject = uuid.uuid4()
        assert str(VaultScope.organization(subject)) == f"org:{subject}"
        assert str(VaultScope.user(subject)) == f"user:{subject}"

    def test_the_constructors_agree_with_the_kinds(self):
        assert VaultScope.organization(uuid.uuid4()).kind is VaultScopeKind.ORGANIZATION
        assert VaultScope.user(uuid.uuid4()).kind is VaultScopeKind.USER


class TestMalformedInput:
    def test_garbage_is_reported_as_malformed(self):
        with pytest.raises(BadRequestError) as exc:
            unseal("not-json", scope=_org())
        assert "malformed" in exc.value.message

    def test_envelope_missing_fields_is_malformed(self):
        with pytest.raises(BadRequestError):
            unseal(json.dumps({"v": 1}), scope=_org())


class TestRotation:
    def test_rewrap_preserves_the_secret(self, three_master_keys):
        scope = _org()
        sealed = seal("sk-live-abcd1234", scope=scope, key_version=1)
        rotated = rewrap(sealed.ciphertext, scope=scope, from_version=1, to_version=2)
        assert unseal(rotated, scope=scope, key_version=2) == "sk-live-abcd1234"

    def test_rewrap_leaves_the_payload_untouched(self, three_master_keys):
        """Rotation re-seals the data key only - that is what makes it cheap."""
        scope = _org()
        sealed = seal("sk-live-abcd1234", scope=scope, key_version=1)
        rotated = rewrap(sealed.ciphertext, scope=scope, from_version=1, to_version=2)
        assert json.loads(sealed.ciphertext)["p"] == json.loads(rotated)["p"]
        assert json.loads(sealed.ciphertext)["k"] != json.loads(rotated)["k"]

    def test_a_secret_sealed_under_the_old_master_key_survives_a_real_rotation(self, monkeypatch):
        """The regression #8 names: the master key actually changes across the rewrap.

        The old suite passed because the master key never changed - `rewrap`
        derived both sides from the single current setting, so it proved
        version-tag bumping, not rotation. Here the envelope is sealed under key
        A, key B becomes current, and the rewrapped envelope must open under B -
        even after A is dropped from the configuration.
        """
        scope = _org()
        monkeypatch.setattr(settings, "VAULT_MASTER_KEYS", {1: KEY_A})
        sealed = seal("sk-live-abcd1234", scope=scope)
        assert sealed.key_version == 1

        monkeypatch.setattr(settings, "VAULT_MASTER_KEYS", {1: KEY_A, 2: KEY_B})
        rotated = rewrap(sealed.ciphertext, scope=scope, from_version=1, to_version=2)
        assert unseal(rotated, scope=scope, key_version=2) == "sk-live-abcd1234"

        monkeypatch.setattr(settings, "VAULT_MASTER_KEYS", {2: KEY_B})
        assert unseal(rotated, scope=scope, key_version=2) == "sk-live-abcd1234"

    def test_rotation_refuses_a_version_with_no_configured_key(self, monkeypatch):
        """Dropping the old key before every row moved off it must be loud.

        Deriving *something* for an unknown version is the old behaviour, and it
        is what made rotation destructive: the derived key opens nothing, so
        every envelope failed as "wrong master key" with the real cause - a
        missing configuration entry - never named.
        """
        scope = _org()
        monkeypatch.setattr(settings, "VAULT_MASTER_KEYS", {1: KEY_A})
        sealed = seal("sk-live-abcd1234", scope=scope)

        monkeypatch.setattr(settings, "VAULT_MASTER_KEYS", {2: KEY_B})
        with pytest.raises(ConfigurationError) as refused:
            rewrap(sealed.ciphertext, scope=scope, from_version=1, to_version=2)
        assert refused.value.details == {"key_version": 1}

        with pytest.raises(ConfigurationError):
            unseal(sealed.ciphertext, scope=scope, key_version=1)

    def test_a_malformed_envelope_cannot_be_rotated(self):
        """Rotation walks every stored secret; one unreadable row has to stop it.

        Passing the value through unchanged would leave a secret still sealed
        under the old master key long after the rotation was declared done.
        """
        with pytest.raises(BadRequestError) as refused:
            rewrap("not-json", scope=_org(), from_version=1, to_version=2)
        assert "malformed" in refused.value.message

    def test_an_envelope_with_no_wrapped_key_cannot_be_rotated(self):
        with pytest.raises(BadRequestError, match="malformed"):
            rewrap(
                json.dumps({"v": 1, "p": "payload"}),
                scope=_org(),
                from_version=1,
                to_version=2,
            )

    def test_rotating_from_the_wrong_version_fails_instead_of_writing_an_unreadable_secret(
        self, three_master_keys
    ):
        """Re-sealing a data key it could not unwrap would produce a row nobody can decrypt.

        The envelope records the version that sealed it precisely so a staged
        rotation can tell which secrets it has already moved; being wrong about
        that has to be loud, because the damage is only noticed at the provider.
        """
        scope = _org()
        sealed = seal("sk-live-abcd1234", scope=scope, key_version=1)

        with pytest.raises(BadRequestError) as refused:
            rewrap(sealed.ciphertext, scope=scope, from_version=2, to_version=3)

        assert "unwrap" in refused.value.message
        assert unseal(sealed.ciphertext, scope=scope) == "sk-live-abcd1234"

    def test_another_organizations_envelope_cannot_be_rotated_into_this_one(self):
        sealed = seal("sk-live-abcd1234", scope=_org())

        with pytest.raises(BadRequestError, match="unwrap"):
            rewrap(sealed.ciphertext, scope=_org(), from_version=1, to_version=2)

    def test_old_version_stops_working_after_rotation(self, three_master_keys):
        scope = _org()
        sealed = seal("sk-live-abcd1234", scope=scope, key_version=1)
        rotated = rewrap(sealed.ciphertext, scope=scope, from_version=1, to_version=2)
        with pytest.raises(BadRequestError):
            unseal(rotated, scope=scope, key_version=1)


class TestCurrentVersion:
    def test_seal_defaults_to_the_highest_configured_version(self, three_master_keys):
        scope = _org()
        sealed = seal("sk-live-abcd1234", scope=scope)
        assert sealed.key_version == 3
        assert unseal(sealed.ciphertext, scope=scope, key_version=3) == "sk-live-abcd1234"

    def test_seal_fields_defaults_to_the_highest_configured_version(self, three_master_keys):
        scope = _org()
        sealed, version = seal_fields({"token": "sk-live-abcd"}, scope=scope)
        assert version == 3
        assert unseal(sealed["token"].ciphertext, scope=scope, key_version=3) == "sk-live-abcd"

    def test_a_single_master_key_is_version_one(self):
        assert current_key_version() == 1

    def test_the_explicit_map_wins_over_the_single_key(self, monkeypatch):
        """`VAULT_MASTER_KEYS`, when set, is the whole truth - config validation
        refuses both settings at once, so the guard here is for tests and for
        anything that mutates settings at runtime."""
        monkeypatch.setattr(settings, "VAULT_MASTER_KEYS", {1: KEY_A, 4: KEY_B})
        assert current_key_version() == 4


class TestLegacyEnvelopes:
    """Envelopes written before the HKDF derivation must stay readable.

    Every deployment older than this change holds only version-1 envelopes, so
    "switch the KDF" without reading the old format would be the same defect as
    8b under another name: an upgrade that makes every stored credential
    unreadable.
    """

    def test_a_sha256_envelope_still_opens(self):
        scope = _org()
        legacy = _legacy_seal("sk-live-abcd1234", scope=scope)
        assert unseal(legacy, scope=scope) == "sk-live-abcd1234"

    def test_an_envelope_without_a_version_tag_reads_as_legacy(self):
        scope = _org()
        envelope = json.loads(_legacy_seal("sk-live-abcd1234", scope=scope))
        del envelope["v"]
        assert unseal(json.dumps(envelope), scope=scope) == "sk-live-abcd1234"

    def test_rewrap_upgrades_a_legacy_envelope_in_place(self):
        """`from_version == to_version` is the format upgrade: same master key,
        new derivation - which is what lets `vault-rotate` move a deployment off
        the bare-SHA-256 wrapping without minting a new master key."""
        scope = _org()
        legacy = _legacy_seal("sk-live-abcd1234", scope=scope)
        upgraded = rewrap(legacy, scope=scope, from_version=1, to_version=1)
        assert json.loads(upgraded)["v"] == ENVELOPE_VERSION
        assert unseal(upgraded, scope=scope, key_version=1) == "sk-live-abcd1234"

    def test_a_rotated_legacy_envelope_opens_under_the_new_key(self, three_master_keys):
        scope = _org()
        legacy = _legacy_seal("sk-live-abcd1234", scope=scope, key_version=1)
        rotated = rewrap(legacy, scope=scope, from_version=1, to_version=3)
        assert unseal(rotated, scope=scope, key_version=3) == "sk-live-abcd1234"

    def test_an_envelope_from_a_newer_format_is_refused(self):
        scope = _org()
        envelope = json.loads(seal("sk-live-abcd1234", scope=scope).ciphertext)
        envelope["v"] = ENVELOPE_VERSION + 1
        with pytest.raises(BadRequestError, match="malformed"):
            unseal(json.dumps(envelope), scope=scope)
        with pytest.raises(BadRequestError, match="malformed"):
            rewrap(json.dumps(envelope), scope=scope, from_version=1, to_version=1)


class TestNeedsRotation:
    def test_a_current_envelope_does_not(self):
        sealed = seal("sk-live-abcd1234", scope=_org())
        assert not needs_rotation(sealed.ciphertext, key_version=sealed.key_version)

    def test_an_old_key_version_does(self, three_master_keys):
        sealed = seal("sk-live-abcd1234", scope=_org(), key_version=1)
        assert needs_rotation(sealed.ciphertext, key_version=1)

    def test_a_legacy_envelope_does_even_at_the_current_version(self):
        legacy = _legacy_seal("sk-live-abcd1234", scope=_org())
        assert needs_rotation(legacy, key_version=1)

    def test_unparseable_ciphertext_does_so_the_sweep_fails_loudly_at_rewrap(self):
        assert needs_rotation("not-json", key_version=1)
        assert needs_rotation("[1]", key_version=1)


def test_generated_master_key_is_long_enough_to_matter():
    assert len(generate_master_key()) >= 43
