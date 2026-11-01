"""`html.parse`: HTML - a mail body, a fetched page - as its text, its links and
what a CSS selector picks.

The input is either the HTML itself (`html`, at most 2,000,000 characters) or a
file holding it (`file`, at most 5,000,000 bytes, checked on the file's row
before its bytes are read) - exactly one. A file is decoded from what its own
`<meta charset>`, byte-order mark or bytes say - lossily if need be, so a PDF is
read as garbled text, not refused - and its declared type is not checked: HTML is
stored as `text/plain`, so any file the run may read is parsed. A NUL character
is read as U+FFFD, as a browser does. A missing file or one over the limit fails
with the file steps' `FILE_NOT_FOUND` and `FILE_TOO_LARGE`; a step with no settings
or no input fails with `HTML_PARSE_NOT_CONFIGURED`. Nothing here raises, and a
malformed or deeply nested page is read as far as it goes.

Where it runs: the parse is done by `_child.py` in a child process of its own
session, not in this one - a descendant selector over deeply nested markup can
take minutes, and a thread cannot be stopped. The child has `PARSE_DEADLINE_SECONDS`
(20) of wall-clock time, a CPU limit a few seconds past it and 2 GiB of address
space. When the deadline passes the child's process group is killed and the step
fails with `HTML_TOO_COMPLEX`, not retryable; a cancelled step kills it too. A
child that cannot be started, dies, or gives an answer that is not valid, and
bytes no decoder yields any text for, fail with `HTML_NOT_READABLE`, its `reason`
detail (`not_started`, `reader_failed`, `invalid_output`, `not_text`) saying
which; no markup and nothing the child printed is kept in an error.

What the output holds:

- `title`: the page's `<title>`, cut at 500 characters, `None` when it has none.
- `text`: the readable text as Markdown - headings, lists and code kept; `script`,
  `style`, `noscript`, `template`, `svg`, `nav`, `footer` and `head` left out - read
  by the same reader the web connector gives a knowledge collection, so a page
  reads alike in both. Cut at `max_chars`, and `text_truncated` says so.
- `links`: every `a[href]` in document order, `href` resolved against `base_url`
  when one is set and kept as written (trimmed) when not, each `href` once with
  the anchor text of its first occurrence (cut at 500 characters, read from the
  anchor's first 100 nodes). A link to a
  `javascript:`, `vbscript:` or `data:` address, an `href` over 2048 characters
  and one that cannot be parsed as an address are left out, so a later step that
  requests every link is never handed a script. Only the first 5,000 anchors are
  looked at and at most 500 links are kept; `links_truncated` says whether the
  page had more.
- `matches`: the elements `selector` picks, in document order, at most
  `max_matches`: their text (cut at 10,000 characters), their outer HTML (cut at
  10,000; both read from the element's first 2,000 nodes, the HTML closed where
  that ends; a `<script>` element's text is its script), and their first 50 attributes with a multi-valued one such as `class`
  joined by spaces and each value cut at 2,000 characters. `match_count` is how
  many elements the selector picked before the cut. Both are empty without a
  selector.

Nothing is fetched and nothing runs: no image, stylesheet, `base_url` or link is
requested, a script is text, and the parser is the standard library's - not an
XML parser, so no entity is expanded from outside the page. Every field is
bounded, and so is the work done for each anchor and each match, which keeps one
hostile page from making the step slow or its output large; an output that is
still over the node output ceiling fails the step as the dispatcher's
`NODE_OUTPUT_TOO_LARGE`.
"""

import asyncio
import contextlib
import json
import os
import signal
import sys
from pathlib import Path
from typing import Final
from urllib.parse import urlsplit

import soupsieve
from bs4.dammit import UnicodeDammit
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from app.workflows import files
from app.workflows.contracts.io import FileRef
from app.workflows.contracts.results import Completed, Failed, NodeResult, WorkflowError
from app.workflows.nodes.html_parse import _child
from app.workflows.nodes.html_parse._child import (
    MAX_ANCHOR_NODES,
    MAX_ANCHORS_SCANNED,
    MAX_ATTRIBUTE_CHARS,
    MAX_ATTRIBUTES,
    MAX_HREF_CHARS,
    MAX_LINK_TEXT_CHARS,
    MAX_LINKS,
    MAX_MATCH_HTML_CHARS,
    MAX_MATCH_NODES,
    MAX_MATCH_TEXT_CHARS,
    MAX_TITLE_CHARS,
)

__all__ = [
    "MAX_ANCHORS_SCANNED",
    "MAX_ANCHOR_NODES",
    "MAX_ATTRIBUTES",
    "MAX_ATTRIBUTE_CHARS",
    "MAX_HREF_CHARS",
    "MAX_LINKS",
    "MAX_LINK_TEXT_CHARS",
    "MAX_MATCH_HTML_CHARS",
    "MAX_MATCH_NODES",
    "MAX_MATCH_TEXT_CHARS",
    "MAX_TITLE_CHARS",
    "HtmlLink",
    "HtmlMatch",
    "HtmlParseConfig",
    "HtmlParseInput",
    "HtmlParseOutput",
    "handle",
]

MAX_HTML_CHARS: Final = 2_000_000
MAX_HTML_BYTES: Final = 5_000_000

# The wall-clock budget of one parse, and what the child may use besides: CPU a
# few seconds past it (the OS stops a child the deadline somehow missed) and
# address space far above any real page (a 2,000,000-character page parses in
# well under 500 MB).
PARSE_DEADLINE_SECONDS: Final = 20
_CPU_MARGIN_SECONDS: Final = 5
_ADDRESS_SPACE_BYTES: Final = 2 * 1024**3
_CHILD_SCRIPT: Final = Path(_child.__file__)

# Run as a fresh, single-threaded Python process between fork and exec, as
# `app/core/office_convert.py` does: it sets the resource limits (skipping any
# the platform will not accept) and `execv`s the parser. A string, because it runs
# only in the child.
_LAUNCHER = """
import os, resource, sys
cpu, address_space = int(sys.argv[1]), int(sys.argv[2])
argv = sys.argv[3:]
for res, value in ((resource.RLIMIT_CPU, cpu), (resource.RLIMIT_AS, address_space)):
    try:
        _, hard = resource.getrlimit(res)
        ceiling = value if hard == resource.RLIM_INFINITY else min(value, hard)
        resource.setrlimit(res, (ceiling, ceiling))
    except (ValueError, OSError):
        pass
os.execv(argv[0], argv)
"""


class HtmlParseConfig(BaseModel):
    """What to pick out of the page and how to resolve its links."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    selector: str | None = Field(
        default=None,
        max_length=500,
        title="CSS selector",
        description=(
            "The elements to pick, as in a stylesheet - for example `table.prices td` or "
            "`a[href^='https']`. Empty picks nothing."
        ),
    )
    max_matches: int = Field(
        default=20,
        ge=1,
        le=200,
        title="Most matches",
        description="How many picked elements to return",
    )
    base_url: str | None = Field(
        default=None,
        max_length=2048,
        title="Base address",
        description="Relative links are resolved against it. It is never fetched.",
    )
    max_chars: int = Field(
        default=100_000,
        ge=1,
        le=500_000,
        title="Most characters of text",
        description="The readable text is cut at this length",
    )

    @field_validator("selector")
    @classmethod
    def _is_a_selector(cls, selector: str | None) -> str | None:
        if selector:
            try:
                soupsieve.compile(selector)
            except soupsieve.SelectorSyntaxError as error:
                raise ValueError(f"This is not a CSS selector: {error}") from error
        return selector

    @field_validator("base_url")
    @classmethod
    def _is_an_http_address(cls, base_url: str | None) -> str | None:
        if base_url is not None:
            try:
                address = urlsplit(base_url)
                host = address.hostname
            except ValueError as error:
                raise ValueError("The base address is not a web address") from error
            if address.scheme not in {"http", "https"} or not host:
                raise ValueError("The base address must be an http or https address with a host")
        return base_url


class HtmlParseInput(BaseModel):
    """The HTML, or a file holding it - exactly one."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    html: str | None = Field(
        default=None,
        max_length=MAX_HTML_CHARS,
        description="The HTML, at most 2,000,000 characters",
    )
    file: FileRef | None = Field(
        default=None, description="A file holding the HTML, at most 5,000,000 bytes"
    )

    @model_validator(mode="after")
    def _exactly_one(self) -> HtmlParseInput:
        if self.html is not None and self.file is not None:
            raise ValueError("Bind either html or file, not both")
        if self.html is None and self.file is None:
            raise ValueError("Bind the html or a file holding it")
        return self


class HtmlLink(BaseModel):
    """One link of the page."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    href: str = Field(description="Where it points, resolved against the base address when set")
    text: str = Field(description="The anchor's text, cut at 500 characters")


class HtmlMatch(BaseModel):
    """One element a selector picked."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = Field(description="The element's text, cut at 10,000 characters")
    html: str = Field(description="The element's outer HTML, cut at 10,000 characters")
    attributes: dict[str, str] = Field(
        description="Its first 50 attributes; a multi-valued one such as `class` is space-joined"
    )


class HtmlParseOutput(BaseModel):
    """The page's title and text, its links and what the selector picked."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str | None = Field(description="The page's `<title>`, or none")
    text: str = Field(description="The readable text as Markdown, without scripts, styles or menus")
    text_truncated: bool = Field(description="Whether the text was cut at the configured length")
    links: list[HtmlLink] = Field(description="Every link once, in document order, at most 500")
    links_truncated: bool = Field(description="Whether the page had more links than were kept")
    matches: list[HtmlMatch] = Field(
        description="The elements the selector picked, in document order; none without a selector"
    )
    match_count: int = Field(description="How many elements the selector picked before the cut")


def _parse(markup: str, config: HtmlParseConfig) -> HtmlParseOutput:
    """The parse itself, in this process and with no deadline: what the child runs."""
    return HtmlParseOutput.model_validate(
        _child.parse(
            markup,
            selector=config.selector,
            max_matches=config.max_matches,
            base_url=config.base_url,
            max_chars=config.max_chars,
        )
    )


def _not_readable(reason: str, message: str, details: dict[str, object] | None = None) -> Failed:
    return Failed(
        error=WorkflowError(
            code="HTML_NOT_READABLE", message=message, details={"reason": reason, **(details or {})}
        )
    )


async def _kill(proc: asyncio.subprocess.Process, pgid: int) -> None:
    """Kill the child's whole process group and reap it, whatever cancels us."""
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pgid, signal.SIGKILL)
    await asyncio.shield(asyncio.ensure_future(proc.wait()))


async def _parse_in_child(markup: str, config: HtmlParseConfig) -> HtmlParseOutput | Failed:
    request = json.dumps(
        {
            "markup": markup,
            "selector": config.selector,
            "max_matches": config.max_matches,
            "base_url": config.base_url,
            "max_chars": config.max_chars,
        }
    ).encode("ascii")
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            _LAUNCHER,
            str(PARSE_DEADLINE_SECONDS + _CPU_MARGIN_SECONDS),
            str(_ADDRESS_SPACE_BYTES),
            sys.executable,
            "-I",
            str(_CHILD_SCRIPT),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        return _not_readable("not_started", "The HTML reader could not be started")
    # The group id is the child's pid: `start_new_session` makes it a leader.
    pgid = proc.pid
    try:
        stdout, _ = await asyncio.wait_for(
            proc.communicate(request), timeout=PARSE_DEADLINE_SECONDS
        )
    except TimeoutError:
        await _kill(proc, pgid)
        return files.failed(
            "HTML_TOO_COMPLEX",
            "This HTML took too long to read - try a simpler selector or a smaller page",
            deadline_seconds=PARSE_DEADLINE_SECONDS,
        )
    except BaseException:
        # Cancelled by the run or its deadline: the child must not outlive the step.
        await _kill(proc, pgid)
        raise
    if proc.returncode != 0:
        return _not_readable(
            "reader_failed",
            "The HTML reader stopped without an answer",
            {"returncode": proc.returncode},
        )
    try:
        return HtmlParseOutput.model_validate_json(stdout)
    except ValidationError:
        return _not_readable("invalid_output", "The HTML reader gave an answer that is not valid")


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    if not isinstance(config, HtmlParseConfig) or not isinstance(node_input, HtmlParseInput):
        return Failed(
            error=WorkflowError(
                code="HTML_PARSE_NOT_CONFIGURED", message="This step needs HTML or a file"
            )
        )
    if node_input.html is not None:
        markup = node_input.html
    else:
        assert node_input.file is not None  # the input model requires one of the two
        stored = await files.load(node_input.file, max_bytes=MAX_HTML_BYTES)
        if isinstance(stored, Failed):
            return stored
        # CPU on up to five megabytes: off the event loop, as the parse is.
        decoded = await asyncio.to_thread(UnicodeDammit, stored.data, is_html=True)
        if decoded.unicode_markup is None:
            return _not_readable(
                "not_text", "This file is not text in any encoding the step can read"
            )
        markup = decoded.unicode_markup
    output = await _parse_in_child(markup, config)
    if isinstance(output, Failed):
        return output
    return Completed[HtmlParseOutput](output=output)
