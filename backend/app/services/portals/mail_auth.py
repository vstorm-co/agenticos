"""Whether a message's sender is who its `From` says - read off the receiver's verdict.

A `sender_contains` filter reads the `From` header, which the sender writes: an
email claiming to come from `ceo@acme.com` costs nothing to send. What the sender
cannot write is the verdict the receiving mail server records after checking
SPF, DKIM and DMARC, in the `Authentication-Results` header (RFC 8601). Gmail and
Exchange Online both write one, and both put it on top: each server prepends its
trace headers, so the topmost is the one our own provider wrote, and a forged
copy the sender pasted into the message sits below it. Only that one is read.

A message is authenticated when DMARC passed, or - for a domain that publishes no
DMARC policy - when a DKIM signature passed for the `From` domain itself or a
parent of it. SPF alone is not enough: it vouches for the envelope sender, which
need not be the address anybody sees.
"""

import re
from collections.abc import Iterable
from email.utils import parseaddr

_COMMENT = re.compile(r"\([^)]*\)")
_RESULT = re.compile(r"^\s*([a-z]+)\s*=\s*([a-z]+)\b(.*)$", re.IGNORECASE | re.DOTALL)
# Exchange names the signer `header.d=acme.com`, Gmail `header.i=@acme.com`.
_SIGNING_DOMAIN = re.compile(r"\bheader\.[di]\s*=\s*([^\s;]+)", re.IGNORECASE)


def authenticated(headers: Iterable[tuple[str, str]], sender: str) -> bool:
    """Whether the topmost `Authentication-Results` vouches for `sender`'s domain.

    `headers` are `(name, value)` in the message's order; `sender` is the `From`
    as the payload carries it, `Name <address>` or a bare address. No verdict at
    all is not authenticated: a filter that asked for a vouched-for sender is not
    satisfied by a message nobody checked.
    """
    verdict = next(
        (value for name, value in headers if name.casefold() == "authentication-results"),
        None,
    )
    _, at, domain = parseaddr(sender)[1].casefold().rpartition("@")
    if verdict is None or not at or not domain:
        return False
    # Gmail opens on the server's own name, which matches no `method=result`;
    # Exchange writes none and opens on its SPF result.
    for clause in _COMMENT.sub("", verdict).split(";"):
        found = _RESULT.match(clause)
        if found is None or found.group(2).casefold() != "pass":
            continue
        method = found.group(1).casefold()
        if method == "dmarc":
            return True
        signer = _SIGNING_DOMAIN.search(found.group(3))
        if (
            method == "dkim"
            and signer is not None
            and _aligned(domain, signer.group(1).rpartition("@")[2])
        ):
            return True
    return False


def _aligned(domain: str, signer: str) -> bool:
    """DMARC's relaxed alignment, near enough: the signer is the domain or a parent of it."""
    signer = signer.casefold().rstrip(".")
    return domain == signer or domain.endswith(f".{signer}")
