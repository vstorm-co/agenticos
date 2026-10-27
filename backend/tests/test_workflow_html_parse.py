"""`html.parse`'s handler, its settings and its registration."""

import ast
import asyncio
import io
import json
import os
import socket
import subprocess
import sys
import time
import warnings
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from bs4 import MarkupResemblesLocatorWarning
from pydantic import ValidationError

from app.workflows import _registry, files
from app.workflows.contracts.io import FileRef
from app.workflows.contracts.results import Completed, Failed
from app.workflows.nodes.html_parse import (
    HtmlParseConfig,
    HtmlParseInput,
    HtmlParseOutput,
    _child,
)
from app.workflows.nodes.html_parse import _handler as html_parse
from app.workflows.nodes.html_parse._handler import handle

pytestmark = pytest.mark.anyio

FIXTURES = Path(__file__).parent / "fixtures" / "html"
PAGE = (FIXTURES / "page.html").read_text(encoding="utf-8")
LATIN1 = (FIXTURES / "latin1.html").read_bytes()
BASE = "https://shop.example.com/store/"


async def _output(html: str = PAGE, **config: object) -> HtmlParseOutput:
    """The parse in this process: what the child process runs, without its start-up."""
    return html_parse._parse(html, HtmlParseConfig(**config))


def _file_ref(data: bytes) -> FileRef:
    return FileRef(file_id=uuid4(), content_type="text/plain", byte_size=len(data))


def _stored(data: bytes) -> files.StoredFile:
    return files.StoredFile(data=data, content_type="text/plain", filename="page.html")


async def test_it_reads_a_pages_title_and_readable_text():
    output = await _output()

    assert output.title == "Spring price list"
    assert "# Seeds and bulbs" in output.text
    assert "- Tulip bulbs" in output.text
    assert "Tulip" in output.text and "3.50" in output.text
    assert "Home menu" not in output.text
    assert "Footer legal text" not in output.text
    assert "INJECTED SCRIPT TEXT" not in output.text
    assert "tracker.invalid" not in output.text
    assert output.text_truncated is False


async def test_it_lists_links_once_each_resolved_against_the_base():
    output = await _output(base_url=BASE)

    hrefs = [link.href for link in output.links]
    assert hrefs == [
        "https://shop.example.com/home",
        "https://shop.example.com/about",
        "https://shop.example.com/orders/track",
        "https://shop.example.com/catalog",
        "mailto:sales@example.com",
    ]
    # The duplicate keeps its first anchor text, and nothing runs or is inlined.
    by_href = {link.href: link.text for link in output.links}
    assert by_href["https://shop.example.com/orders/track"] == "Track an order"
    assert by_href["https://shop.example.com/home"] == "Home menu"
    assert by_href["mailto:sales@example.com"] == "Write to sales"
    assert not any(h.lower().lstrip().startswith(("javascript", "data")) for h in hrefs)
    assert output.links_truncated is False


async def test_without_a_base_relative_links_stay_as_written():
    output = await _output()

    assert [link.href for link in output.links] == [
        "/home",
        "/about",
        "/orders/track",
        "https://shop.example.com/catalog",
        "mailto:sales@example.com",
    ]


@pytest.mark.parametrize(
    "href",
    [
        "javascript:alert(1)",
        "  JavaScript:alert(1)",
        "java\nscript:alert(1)",
        "vbscript:msgbox(1)",
        "data:text/html,<b>x</b>",
        "DATA:text/plain,x",
    ],
)
async def test_a_link_that_runs_or_inlines_something_is_left_out(href: str):
    output = await _output(f'<a href="{href}">x</a><a href="/ok">ok</a>', base_url=BASE)

    assert [link.href for link in output.links] == ["https://shop.example.com/ok"]


async def test_a_link_urljoin_cannot_parse_is_left_out():
    output = await _output('<a href="http://[::1">bad</a><a href="/ok">ok</a>', base_url=BASE)

    assert [link.href for link in output.links] == ["https://shop.example.com/ok"]


async def test_a_selector_picks_its_elements_text_markup_and_attributes():
    output = await _output(selector="table td")

    assert output.match_count == 6
    first = output.matches[0]
    assert first.text == "Tulip"
    assert first.html == '<td class="cell wide" data-sku="T-1">Tulip</td>'
    assert first.attributes == {"class": "cell wide", "data-sku": "T-1"}
    assert [match.text for match in output.matches[:4]] == ["Tulip", "3.50", "Basil", "1.20"]
    assert output.matches[1].attributes == {}


async def test_without_a_selector_nothing_is_picked():
    for config in ({}, {"selector": ""}, {"selector": None, "base_url": None}):
        output = await _output(**config)
        assert output.matches == []
        assert output.match_count == 0


async def test_matches_are_cut_at_the_most_and_counted_before():
    output = await _output(selector="table td", max_matches=2)

    assert [match.text for match in output.matches] == ["Tulip", "3.50"]
    assert output.match_count == 6


async def test_a_match_is_bounded_in_its_text_markup_and_attributes():
    many = " ".join(f'a{n}="{"v" * 3000}"' for n in range(60))
    html = f"<div {many}>{'word ' * 20_000}</div>"

    (match,) = (await _output(html, selector="div")).matches

    assert len(match.text) == html_parse.MAX_MATCH_TEXT_CHARS
    assert len(match.html) == html_parse.MAX_MATCH_HTML_CHARS
    assert len(match.attributes) == html_parse.MAX_ATTRIBUTES
    assert {len(value) for value in match.attributes.values()} == {html_parse.MAX_ATTRIBUTE_CHARS}


async def test_an_invalid_selector_is_refused_when_configured():
    with pytest.raises(ValidationError) as refused:
        HtmlParseConfig(selector="a[href")

    (problem,) = refused.value.errors()
    assert problem["loc"] == ("selector",)
    assert "This is not a CSS selector" in problem["msg"]


@pytest.mark.parametrize(
    "base_url",
    ["file:///etc/passwd", "javascript:x", "shop.example.com", "https://", "http://[::1"],
)
async def test_a_base_that_is_not_http_is_refused(base_url: str):
    with pytest.raises(ValidationError) as refused:
        HtmlParseConfig(base_url=base_url)

    assert refused.value.errors()[0]["loc"] == ("base_url",)


async def test_html_or_a_file_exactly_one():
    ref = _file_ref(b"x")

    with pytest.raises(ValidationError, match="not both"):
        HtmlParseInput(html="<p>x</p>", file=ref)
    with pytest.raises(ValidationError, match="Bind the html or a file holding it"):
        HtmlParseInput()


async def test_html_over_the_limit_is_refused():
    with pytest.raises(ValidationError):
        HtmlParseInput(html="x" * 2_000_001)


async def test_it_reads_html_from_a_file_in_its_own_encoding(monkeypatch: pytest.MonkeyPatch):
    async def load(ref: FileRef, *, max_bytes: int) -> files.StoredFile:
        return _stored(LATIN1)

    monkeypatch.setattr(files, "load", load)

    result = await handle(HtmlParseConfig(), HtmlParseInput(file=_file_ref(LATIN1)))

    assert isinstance(result, Completed)
    assert isinstance(result.output, HtmlParseOutput)
    assert result.output.title == "Grüße aus Kraków"
    assert "Straße über die Brücke, weiße Rose, café à la carte, été." in result.output.text


async def test_a_file_over_the_limit_fails_before_it_is_read(monkeypatch: pytest.MonkeyPatch):
    seen: list[int] = []
    refused = files.failed("FILE_TOO_LARGE", "too big", byte_size=6_000_000)

    async def load(ref: FileRef, *, max_bytes: int) -> Failed:
        seen.append(max_bytes)
        return refused

    monkeypatch.setattr(files, "load", load)

    result = await handle(HtmlParseConfig(), HtmlParseInput(file=_file_ref(b"x")))

    assert result is refused
    assert seen == [html_parse.MAX_HTML_BYTES] == [5_000_000]


async def test_bytes_that_are_no_text_fail_as_not_readable(monkeypatch: pytest.MonkeyPatch):
    # `UnicodeDammit` falls back to a lossy decode, so it answers `None` only for
    # markup it cannot guess at; stand in for that case.
    class Undecodable:
        def __init__(self, data: bytes, *, is_html: bool) -> None:
            self.unicode_markup = None

    async def load(ref: FileRef, *, max_bytes: int) -> files.StoredFile:
        return _stored(b"\x00\x01\x02")

    monkeypatch.setattr(files, "load", load)
    monkeypatch.setattr(html_parse, "UnicodeDammit", Undecodable)

    result = await handle(HtmlParseConfig(), HtmlParseInput(file=_file_ref(b"x")))

    assert isinstance(result, Failed)
    assert result.error.code == "HTML_NOT_READABLE"
    assert result.error.details == {"reason": "not_text"}


async def test_nothing_is_fetched_and_no_script_runs(monkeypatch: pytest.MonkeyPatch):
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("the step touched the network")

    monkeypatch.setattr(httpx.AsyncClient, "send", refuse)
    monkeypatch.setattr(httpx.Client, "send", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)

    output = await _output(base_url=BASE, selector="img")

    assert output.title == "Spring price list"
    assert output.matches[0].attributes["src"] == "https://images.example.com/tulip.png"
    assert "INJECTED SCRIPT TEXT" not in output.text


async def test_text_is_cut_at_its_most_and_says_so():
    output = await _output(f"<p>{'abcdefghij' * 100}</p>", max_chars=250)

    assert len(output.text) == 250
    assert output.text_truncated is True


async def test_text_that_fits_is_not_marked_cut():
    output = await _output("<p>" + "a" * 250 + "</p>", max_chars=250)

    assert len(output.text) == 250
    assert output.text_truncated is False


async def test_links_are_cut_at_five_hundred_and_say_so():
    html = "".join(f'<a href="/p/{n}">page {n}</a>' for n in range(html_parse.MAX_LINKS + 20))

    output = await _output(html)

    assert len(output.links) == html_parse.MAX_LINKS == 500
    assert output.links_truncated is True
    assert output.links[-1].href == "/p/499"


async def test_exactly_five_hundred_links_are_not_marked_cut():
    html = "".join(f'<a href="/p/{n}">page {n}</a>' for n in range(html_parse.MAX_LINKS))

    output = await _output(html)

    assert len(output.links) == 500
    assert output.links_truncated is False


async def test_an_overlong_href_is_left_out_and_its_text_is_cut():
    long_href = "/" + "a" * html_parse.MAX_HREF_CHARS
    html = f'<a href="{long_href}">no</a><a href="/ok">{"t" * 900}</a>'

    output = await _output(html)

    assert [link.href for link in output.links] == ["/ok"]
    assert len(output.links[0].text) == html_parse.MAX_LINK_TEXT_CHARS


async def test_a_title_is_bounded():
    output = await _output(f"<title>{'t' * 5000}</title><p>x</p>")

    assert output.title is not None
    assert len(output.title) == html_parse.MAX_TITLE_CHARS


async def test_a_page_with_no_title_has_none():
    assert (await _output("<p>just text</p>")).title is None


async def test_deeply_nested_markup_completes():
    result = await handle(HtmlParseConfig(selector="div"), HtmlParseInput(html="<div>" * 50_000))

    assert isinstance(result, Completed)
    assert isinstance(result.output, HtmlParseOutput)
    assert result.output.match_count == 50_000
    assert len(result.output.matches) == 20


async def test_markup_that_looks_like_an_address_is_still_markup():
    # bs4 warns on a string that resembles a URL or a filename; none of it may
    # reach the log, or raise where warnings are errors.
    with warnings.catch_warnings():
        warnings.simplefilter("error", MarkupResemblesLocatorWarning)
        assert (await _output("http://example.com/page")).links == []
        assert (await _output("page.html")).links == []


def test_markup_that_opens_as_xml_raises_no_warning_in_a_fresh_process():
    # pytest resets the warning filters around every test, which drops the one the
    # module installs at import; a fresh interpreter is where it can be seen.
    script = (
        "import warnings\n"
        "import app.services.workflow_execution\n"
        "from app.workflows.nodes.html_parse import _child\n"
        "with warnings.catch_warnings(record=True) as caught:\n"
        '    out = _child.parse(\'<?xml version="1.0"?><a href="/x">x</a>\',\n'
        "        selector=None, max_matches=1, base_url=None, max_chars=10)\n"
        "print(out['links'][0]['href'], len(caught))\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )

    assert done.stdout.split() == ["/x", "0"]


def test_the_child_loads_no_application_settings_or_connectors():
    # The child is started for every step: importing the settings or the connectors
    # package would build and validate `Settings()` and import five connectors each time.
    script = (
        "import runpy, sys\n"
        "runpy.run_path(sys.argv[1], run_name='child_import_check')\n"
        "print(sorted(name for name in sys.modules if name.startswith('app.')))\n"
    )
    done = subprocess.run(
        [sys.executable, "-I", "-c", script, str(html_parse._CHILD_SCRIPT)],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )

    loaded = ast.literal_eval(done.stdout.strip())
    assert "app.core.config" not in loaded
    assert not [name for name in loaded if name.startswith("app.services.rag.connectors")]
    assert "app.services.rag.web_page" in loaded


@pytest.mark.parametrize(
    ("html", "links", "first"),
    [
        ('<a href="x">' * 150_000, 1, "x"),
        ('<a href="x">t' * 150_000, 1, "x"),
        ("".join(f'<a href="{n}">t' for n in range(100_000)), html_parse.MAX_LINKS, "0"),
    ],
    ids=["no-text-same-href", "text-same-href", "text-unique-hrefs"],
)
async def test_unclosed_anchors_nested_in_each_other_complete(html: str, links: int, first: str):
    # html.parser nests every unclosed `<a>` in the one before it, so the text of
    # each anchor used to be a walk over every anchor after it.
    output = await _output(html)

    assert len(output.links) == links
    assert output.links[0].href == first
    assert output.links_truncated is True


async def test_a_page_with_more_anchors_than_are_scanned_says_so():
    html = '<a href="same">a</a>' * (html_parse.MAX_ANCHORS_SCANNED + 1)

    assert (await _output(html)).links_truncated is True
    assert (await _output(html[: -len('<a href="same">a</a>')])).links_truncated is False


async def test_a_nul_is_read_as_a_replacement_character():
    output = await _output('<title>a\x00b</title><p class="c\x00d">e\x00f</p>', selector="p")

    assert output.title == "a\ufffdb"
    assert output.text == "e\ufffdf"
    assert output.matches[0].text == "e\ufffdf"
    assert output.matches[0].attributes == {"class": "c\ufffdd"}
    assert "\x00" not in output.model_dump_json()


async def test_a_matchs_text_leaves_out_comments_scripts_and_styles():
    html = "<div><!-- hidden -->one<script>run()</script><b> two </b><style>p{}</style></div>"

    (match,) = (await _output(html, selector="div")).matches

    assert match.text == "one two"


async def test_a_matchs_markup_is_closed_where_its_node_budget_ends(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(_child, "MAX_MATCH_NODES", 5)
    html = "<ul>" + "<li>x</li>" * 50 + "</ul>"

    (match,) = (await _output(html, selector="ul")).matches

    assert match.html == "<ul><li>x</li><li>x</li></ul>"
    assert match.text == "x x"


async def test_a_script_elements_own_text_is_its_script():
    html = (
        '<script type="application/ld+json">{"@type": "Product"}</script>'
        "<style>p { color: red }</style><template><i>t</i></template>"
    )

    scripts = (await _output(html, selector="script")).matches
    styles = (await _output(html, selector="style")).matches
    templates = (await _output(html, selector="template")).matches

    assert scripts[0].text == '{"@type": "Product"}'
    assert scripts[0].attributes == {"type": "application/ld+json"}
    assert styles[0].text == "p { color: red }"
    assert templates[0].text == "t"


async def test_a_huge_text_is_cut_before_it_is_serialised():
    # Entity-escaping two million `&` for each of 200 matches took over a minute.
    html = "<div>" * 200 + "&" * 1_999_000
    started = time.monotonic()

    output = await _output(html, selector="div", max_matches=200)

    assert time.monotonic() - started < 30
    assert output.match_count == 200
    assert len(output.matches) == 200
    first = output.matches[0].html
    assert len(first) == html_parse.MAX_MATCH_HTML_CHARS
    assert first.startswith("<div><div>")
    assert "&amp;" in first


async def test_a_string_over_the_budget_is_cut_inside_its_open_tags(
    monkeypatch: pytest.MonkeyPatch,
):
    # The cut string keeps its parent; without it bs4 would close `<p><b>` before
    # it, and the markup would read `<p><b></b></p>aaaa...`.
    monkeypatch.setattr(_child, "MAX_MATCH_HTML_CHARS", 20)
    html = "<p><b>" + "a" * 50 + "</b>tail</p>"

    (match,) = (await _output(html, selector="p")).matches

    assert match.html == "<p><b>" + "a" * 14


async def test_a_string_that_exactly_fills_the_budget_ends_the_markup(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(_child, "MAX_MATCH_HTML_CHARS", 30)
    html = "<p>" + "a" * 30 + "<b>more</b></p>"

    (match,) = (await _output(html, selector="p")).matches

    assert match.html == "<p>" + "a" * 27


class _Spawns:
    """The processes `handle` starts, recorded by wrapping the real spawn."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.procs: list[asyncio.subprocess.Process] = []
        real = asyncio.create_subprocess_exec

        async def spawn(*args: str, **kwargs: object) -> asyncio.subprocess.Process:
            proc = await real(*args, **kwargs)  # ty: ignore[invalid-argument-type]
            self.procs.append(proc)
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)

    def assert_gone(self) -> None:
        for proc in self.procs:
            assert proc.returncode is not None
            with pytest.raises(ProcessLookupError):
                os.killpg(proc.pid, 0)


async def test_the_step_parses_in_a_child_process(monkeypatch: pytest.MonkeyPatch):
    spawns = _Spawns(monkeypatch)

    result = await handle(
        HtmlParseConfig(selector="table td", base_url=BASE), HtmlParseInput(html=PAGE)
    )

    assert isinstance(result, Completed)
    assert result.output == html_parse._parse(
        PAGE, HtmlParseConfig(selector="table td", base_url=BASE)
    )
    assert result.output.title == "Spring price list"
    assert len(spawns.procs) == 1
    assert spawns.procs[0].pid != os.getpid()
    spawns.assert_gone()


async def test_a_selector_that_never_finishes_fails_as_too_complex(
    monkeypatch: pytest.MonkeyPatch,
):
    # soupsieve backtracks without memoising: `p div` over 20,000 nested divs takes
    # minutes. The deadline is shortened so the test does not wait for it.
    monkeypatch.setattr(html_parse, "PARSE_DEADLINE_SECONDS", 1)
    spawns = _Spawns(monkeypatch)
    started = time.monotonic()

    result = await handle(
        HtmlParseConfig(selector="p div"), HtmlParseInput(html="<p>" + "<div>" * 20_000)
    )

    assert time.monotonic() - started < 15
    assert isinstance(result, Failed)
    assert result.error.code == "HTML_TOO_COMPLEX"
    assert result.error.retryable is False
    assert result.error.message == (
        "This HTML took too long to read - try a simpler selector or a smaller page"
    )
    assert result.error.details == {"deadline_seconds": 1}
    spawns.assert_gone()


def _child_script(tmp_path: Path, source: str) -> Path:
    script = tmp_path / "child.py"
    script.write_text(source, encoding="utf-8")
    return script


@pytest.mark.parametrize(
    ("source", "details"),
    [
        (
            "import sys; sys.stderr.write('<p>SECRET</p>'); sys.exit(3)",
            {"reason": "reader_failed", "returncode": 3},
        ),
        ("print('not json at all <p>SECRET</p>')", {"reason": "invalid_output"}),
        ("print('{\"title\": 1}')", {"reason": "invalid_output"}),
    ],
    ids=["exits-with-an-error", "prints-garbage", "prints-the-wrong-shape"],
)
async def test_a_child_that_fails_or_answers_badly_is_not_readable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, source: str, details: dict[str, object]
):
    monkeypatch.setattr(html_parse, "_CHILD_SCRIPT", _child_script(tmp_path, source))

    result = await handle(HtmlParseConfig(), HtmlParseInput(html="<p>SECRET</p>"))

    assert isinstance(result, Failed)
    assert result.error.code == "HTML_NOT_READABLE"
    assert result.error.details == details
    assert "SECRET" not in result.error.message


async def test_a_child_that_cannot_be_started_is_not_readable(monkeypatch: pytest.MonkeyPatch):
    async def refuse(*args: object, **kwargs: object) -> None:
        raise OSError("no processes left")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", refuse)

    result = await handle(HtmlParseConfig(), HtmlParseInput(html="<p>x</p>"))

    assert isinstance(result, Failed)
    assert result.error.code == "HTML_NOT_READABLE"
    assert result.error.details == {"reason": "not_started"}


async def test_cancelling_the_step_kills_the_child(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    pid_file = tmp_path / "pid"
    monkeypatch.setenv("PID_FILE", str(pid_file))
    monkeypatch.setattr(
        html_parse,
        "_CHILD_SCRIPT",
        _child_script(
            tmp_path,
            "import os, time\n"
            "open(os.environ['PID_FILE'], 'w').write(str(os.getpid()))\n"
            "time.sleep(60)\n",
        ),
    )
    spawns = _Spawns(monkeypatch)
    task = asyncio.create_task(handle(HtmlParseConfig(), HtmlParseInput(html="<p>x</p>")))
    for _ in range(300):
        if pid_file.exists() and pid_file.read_text():
            break
        await asyncio.sleep(0.05)
    assert pid_file.exists()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    spawns.assert_gone()
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_file.read_text()), 0)


def test_the_child_program_answers_its_request_on_stdout():
    request = {
        "markup": PAGE,
        "selector": "table td",
        "max_matches": 2,
        "base_url": BASE,
        "max_chars": 1000,
    }
    stdout = io.BytesIO()

    _child.main(io.BytesIO(json.dumps(request).encode()), stdout)

    answer = html_parse.HtmlParseOutput.model_validate_json(stdout.getvalue())
    assert answer == html_parse._parse(
        PAGE, HtmlParseConfig(selector="table td", max_matches=2, base_url=BASE, max_chars=1000)
    )


@pytest.mark.parametrize(
    ("config", "node_input"),
    [
        (None, HtmlParseInput(html="<p>x</p>")),
        (HtmlParseConfig(), None),
    ],
)
async def test_without_its_settings_it_says_so(
    config: HtmlParseConfig | None, node_input: HtmlParseInput | None
):
    result = await handle(config, node_input)

    assert isinstance(result, Failed)
    assert result.error.code == "HTML_PARSE_NOT_CONFIGURED"
    assert result.error.message == "This step needs HTML or a file"


async def test_the_step_is_registered_in_the_data_group():
    _registry.load_builtins()

    definition = _registry.get("html.parse", 1)

    assert definition.category == "data"
    assert definition.name == "Parse HTML"
    assert definition.effect_kind == "read"
    assert definition.retry_guarantee == "idempotent"
    assert [(port.id, port.kind) for port in definition.ports] == [
        ("in", "input"),
        ("out", "output"),
    ]
    assert definition.config_schema is HtmlParseConfig
    assert definition.output_schema is HtmlParseOutput
