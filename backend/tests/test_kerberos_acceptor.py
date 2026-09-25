"""The Kerberos ticket acceptor, over a stand-in `gssapi` (#1773).

`gssapi` is the `kerberos` extra, which CI does not install - it builds against
the system Kerberos libraries. So the module is replaced in `sys.modules` with a
fake that records how the acceptor drives it. What that cannot show is a real
KDC accepting a real ticket; that was checked by hand against an MIT KDC when
this landed (#1773): a real SPNEGO token accepted, one for another service refused.
"""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import pytest

from app.core.exceptions import ConfigurationError
from app.services.directory.contract import TicketRejected
from app.services.directory.kerberos import GssapiTicketAcceptor


class _GSSError(Exception):
    pass


class _Context:
    def __init__(self, *, complete: bool, answer: bytes | None, fail: bool) -> None:
        self.complete = False
        self._completes = complete
        self._answer = answer
        self._fail = fail
        self.initiator_name = "jane@CORP.EXAMPLE"
        self.stepped: list[bytes] = []

    def step(self, token: bytes) -> bytes | None:
        self.stepped.append(token)
        if self._fail:
            raise _GSSError("Decrypt integrity check failed for HTTP/host@CORP.EXAMPLE")
        self.complete = self._completes
        return self._answer


def _fake_gssapi(*, complete: bool = True, answer: bytes | None = b"mutual", fail: bool = False):
    calls: dict[str, object] = {}
    context = _Context(complete=complete, answer=answer, fail=fail)
    module = ModuleType("gssapi")
    exceptions = ModuleType("gssapi.exceptions")
    exceptions.GSSError = _GSSError  # type: ignore[attr-defined]

    def name(value: str, kind: object) -> tuple[str, object]:
        return (value, kind)

    def credentials(**kwargs: object) -> str:
        calls["credentials"] = kwargs
        return "creds"

    def security_context(**kwargs: object) -> _Context:
        calls["context"] = kwargs
        return context

    module.Name = name  # type: ignore[attr-defined]
    module.NameType = SimpleNamespace(kerberos_principal="krb5-principal")  # type: ignore[attr-defined]
    module.Credentials = credentials  # type: ignore[attr-defined]
    module.SecurityContext = security_context  # type: ignore[attr-defined]
    module.exceptions = exceptions  # type: ignore[attr-defined]
    return module, exceptions, calls, context


@pytest.fixture
def install(monkeypatch):
    def _install(**kwargs):
        module, exceptions, calls, context = _fake_gssapi(**kwargs)
        monkeypatch.setitem(sys.modules, "gssapi", module)
        monkeypatch.setitem(sys.modules, "gssapi.exceptions", exceptions)
        return calls, context

    return _install


def test_an_accepted_ticket_names_its_principal_and_the_answer(install):
    calls, context = install()
    acceptor = GssapiTicketAcceptor(
        keytab="/etc/agenticos.keytab", service_principal="HTTP/agenticos.corp.example@CORP.EXAMPLE"
    )

    ticket = acceptor.accept(b"spnego-token")

    assert ticket.principal == "jane@CORP.EXAMPLE"
    assert ticket.response_token == b"mutual"
    assert context.stepped == [b"spnego-token"]
    assert calls["credentials"] == {
        "name": ("HTTP/agenticos.corp.example@CORP.EXAMPLE", "krb5-principal"),
        "usage": "accept",
        "store": {"keytab": "/etc/agenticos.keytab"},
    }
    assert calls["context"] == {"creds": "creds", "usage": "accept"}


def test_without_a_keytab_or_principal_the_defaults_are_used(install):
    calls, _ = install()

    GssapiTicketAcceptor(keytab=None, service_principal=None).accept(b"t")

    assert calls["credentials"] == {"name": None, "usage": "accept", "store": None}


@pytest.mark.security
def test_a_ticket_the_library_rejects_is_rejected_without_its_text(install):
    install(fail=True)

    with pytest.raises(TicketRejected) as refused:
        GssapiTicketAcceptor(keytab=None, service_principal=None).accept(b"forged")

    assert "CORP.EXAMPLE" not in refused.value.message


@pytest.mark.security
def test_a_token_needing_a_second_leg_is_rejected(install):
    """Kerberos completes in one leg; a continuation is NTLM or something worse."""
    install(complete=False)

    with pytest.raises(TicketRejected):
        GssapiTicketAcceptor(keytab=None, service_principal=None).accept(b"ntlm-negotiate")


def test_a_deployment_without_the_extra_is_told_which_extra(monkeypatch):
    monkeypatch.setitem(sys.modules, "gssapi", None)

    with pytest.raises(ConfigurationError) as refused:
        GssapiTicketAcceptor(keytab=None, service_principal=None).accept(b"t")

    assert "kerberos" in refused.value.message
