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
    """
    local = replace(
        web_fetch_tool(
            max_content_length=max_content_chars,
            timeout=_TIMEOUT_SECONDS,
            max_download_bytes=_MAX_DOWNLOAD_BYTES,
            allowed_domains=allowed_domains,
            blocked_domains=blocked_domains,
        ),
        description=FETCH_DESCRIPTION,
    )
    return WebFetch(
        native=method in ("auto", "native"),
        local=False if method == "native" else local,
        allowed_domains=allowed_domains,
        blocked_domains=blocked_domains,
    )
