"""Reading the page behind a URL.

`web_research` returns titles, URLs and snippets. Until this existed an agent
could find a source and not read it, so it answered from the snippet and cited a
page it had never opened (agenticos#51).

The fetch is Pydantic AI's `web_fetch_tool` rather than one written here, and
that is a security decision before it is a convenience one. The URL comes from
the *model*, and it is dereferenced from inside the container, which is the
server-side request forgery case `app.core.sanitize.validate_webhook_url`
exists for. Validating a URL and then handing it to `httpx` is weaker than it
looks: `httpx` resolves the hostname a second time, and follows redirects
without asking again. Their `pydantic_ai._ssrf.safe_download` closes both - it
pins the address it resolved into the request, so there is no window left to
rebind in, and it re-validates every redirect hop, the domain filters included.
It also bounds the body as it streams and refuses the compression encodings that
cannot be bounded that way. A fetch built on `validate_webhook_url` would have
none of the three.

What is still this repository's is the text the model reads: the description is
declared here and handed to the library, the same bargain `sandbox` and
`planning` make, so an author rewording it edits one file rather than somebody
else's package.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Literal

from pydantic_ai.capabilities import WebFetch
from pydantic_ai.common_tools.web_fetch import web_fetch_tool

FetchMethod = Literal["local", "auto", "native"]

# The methods under which the model provider dereferences the URL rather than
# this deployment. `auto` is one of them even though it only *may* be: whether a
# model has a native fetch is a property of the model profile, which changes
# without republishing the agent, so anything reasoning about who executes the
# fetch has to read `auto` as "possibly the provider".
PROVIDER_EXECUTED_METHODS: frozenset[str] = frozenset({"auto", "native"})

FETCH_DESCRIPTION = (
    "Read the full page at a URL, as Markdown. Use it after a search to read a "
    "result rather than answering from its snippet, and whenever the user gives a "
    "link. One URL per call; follow a link you find by calling it again."
)

# Long enough for a slow page to finish rendering, short enough that a hung fetch
# does not hold a conversation open while somebody watches a spinner.
_TIMEOUT_SECONDS = 30

# The body is buffered before anything looks at it, so this is the memory one
# tool call can cost. The library's own default is 50 MiB, which is five times
# what the largest page worth sending to a model weighs.
_MAX_DOWNLOAD_BYTES = 10 * 1024 * 1024


def a_label(hostname: str) -> str:
    """One hostname as DNS will be asked for it: lower case, no root dot, ASCII.

    The filters compare strings, and a name has more than one spelling, so the
    spelling has to be settled before anything compares. Two of the three are
    settled by the library on the way in - `urlparse` lower-cases the host and
    `extract_host_and_port` strips the root label - and the third is not: a URL
    naming a host in Unicode reaches the comparison as `exämple.com` while the
    only form a bare-hostname filter can hold is the A-label. So a denylist of
    `xn--exmple-cua.com` does not stop `https://exämple.com/`, which is a
    denylist with a hole in it rather than one that reads oddly.

    IDNA 2003, from the standard library, deliberately: `socket.getaddrinfo`
    encodes a Unicode hostname with the same codec, so this is the name that
    would actually be resolved rather than a second opinion about it.

    Raises:
        UnicodeError: If the name has no A-label - an empty label, or one too
            long to encode. The caller reports it as an entry that cannot match.
    """
    return hostname.strip().lower().rstrip(".").encode("idna").decode("ascii")


def _dns_aliases(hostname: str) -> list[str]:
    """Every spelling of one A-label the comparison could be handed.

    The A-label itself, and its Unicode form where they differ - a model asked
    to read `https://exämple.com/` produces the second, and an exact-match
    filter holding only the first lets it through.

    A name that merely *looks* like an A-label has no Unicode form to add, and
    is not refused for it: `xn--a.com` is a hostname somebody may legitimately
    write, and decoding it raises. Raising here would take down the build of an
    agent that published cleanly.
    """
    try:
        unicode_form = hostname.encode("ascii").decode("idna")
    except UnicodeError:
        return [hostname]
    return [hostname] if unicode_form == hostname else [hostname, unicode_form]


def _filter_list(hostnames: list[str] | None) -> list[str] | None:
    return None if hostnames is None else [alias for h in hostnames for alias in _dns_aliases(h)]


def build_web_fetch(
    *,
    method: FetchMethod,
    max_content_chars: int,
    allowed_domains: list[str] | None,
    blocked_domains: list[str] | None,
) -> WebFetch[object]:
    """The fetch capability one binding's configuration asks for.

    `method` decides who dereferences the URL, and the three answers are
    genuinely different agents:

    - `local` - we fetch, guarded as above. The default, because it is the only
      one that behaves identically on every model, which is the same reason
      `web_research` defaults to a search API of ours rather than the provider's.
    - `native` - the provider fetches, with its own egress and its own citations.
      Pydantic AI raises on a model that cannot, which is the right moment to find
      that out.
    - `auto` - native where the model has it, ours everywhere else. The local tool
      is marked `unless_native`, so exactly one of the two is ever offered.

    The domain filters are passed twice on purpose: once to the capability, which
    is what reaches the *native* tool, and once to the local tool we build here.
    `local=True` would apply them to the local tool for us but leaves no way to
    set the content or download bounds, and a filter set on only one of the two
    paths is a filter that lapses the day somebody switches `method`.

    Each configured hostname is expanded to its DNS-equivalent spellings on the
    way through - see :func:`a_label`. The config stores one canonical entry; the
    comparison is handed every form a URL could name it by.
    """
    allowed = _filter_list(allowed_domains)
    blocked = _filter_list(blocked_domains)
    local = replace(
        web_fetch_tool(
            max_content_length=max_content_chars,
            timeout=_TIMEOUT_SECONDS,
            max_download_bytes=_MAX_DOWNLOAD_BYTES,
            allowed_domains=allowed,
            blocked_domains=blocked,
        ),
        description=FETCH_DESCRIPTION,
    )
    return WebFetch(
        native=method in PROVIDER_EXECUTED_METHODS,
        local=False if method == "native" else local,
        allowed_domains=allowed,
        blocked_domains=blocked,
    )
