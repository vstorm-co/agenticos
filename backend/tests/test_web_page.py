"""One page read into text and links (`app/services/rag/connectors/web_page.py`, #984)."""

from app.services.rag.connectors.web_page import parse_page

URL = "https://docs.example.com/guide/intro"


def test_the_structure_a_reader_sees_survives_as_markdown() -> None:
    page = parse_page(
        "<h1>Install</h1><p>Run <b>one</b>\n command.</p>"
        "<ul><li>first<li><p>second</p></ul>"
        "<pre>x = 1\n  y = 2\n</pre><h3>Next</h3><p>More<br>lines</p>",
        URL,
    )

    assert page.markdown == (
        "# Install\n\nRun one command.\n\n- first\n\n- second\n\n```\nx = 1\n  y = 2\n```"
        "\n\n### Next\n\nMore\n\nlines"
    )


def test_chrome_is_not_text_but_its_links_are_followed() -> None:
    page = parse_page(
        "<head><title> The   Guide </title><style>p{}</style></head>"
        '<nav><a href="setup">Setup</a> Menu</nav><script>track()</script>'
        "<p>Body.</p><footer>Copyright</footer>",
        URL,
    )

    assert page.markdown == "Body."
    assert page.title == "The Guide"
    assert page.links == ("https://docs.example.com/guide/setup",)


def test_main_is_the_content_when_a_page_has_one() -> None:
    page = parse_page("<div>Sidebar</div><main><p>The content.</p></main><div>After</div>", URL)

    assert page.markdown == "The content."


def test_a_page_without_main_is_all_content() -> None:
    assert parse_page("<div>One</div><div>Two</div>", URL).markdown == "One\n\nTwo"


def test_an_empty_code_block_is_dropped() -> None:
    assert parse_page("<p>a</p><pre>\n\n</pre>", URL).markdown == "a"


def test_a_nested_code_block_is_fenced_once() -> None:
    assert parse_page("<pre>a<pre>b</pre>c</pre>", URL).markdown == "```\nabc\n```"


def test_links_resolve_against_base_and_skip_rel_nofollow() -> None:
    page = parse_page(
        '<base href="/docs/"><a href="a">a</a><a href="b" rel="external nofollow">b</a><a>none</a>',
        URL,
    )

    assert page.links == ("https://docs.example.com/docs/a",)


def test_meta_robots_says_whether_to_index_and_follow() -> None:
    assert parse_page('<meta name="robots" content="noindex">', URL).index is False
    assert parse_page('<meta name="ROBOTS" content="index, nofollow">', URL).follow is False
    none = parse_page('<meta name="robots" content="none">', URL)
    assert (none.index, none.follow) == (False, False)
    plain = parse_page('<meta name="description" content="noindex">', URL)
    assert (plain.index, plain.follow) == (True, True)


def test_an_unclosed_skip_inside_a_closed_block_does_not_swallow_the_rest() -> None:
    page = parse_page("<div><nav>menu</div><p>Still here.</p></span>", URL)

    assert page.markdown == "Still here."


def test_a_link_urljoin_cannot_parse_is_dropped_not_raised() -> None:
    page = parse_page(
        '<base href="http://[::1"><a href="http://[::1">bad</a><a href="ok">ok</a>', URL
    )

    assert page.links == ("https://docs.example.com/guide/ok",)


def test_markup_the_parser_refuses_keeps_what_came_before_it() -> None:
    page = parse_page("<p>Kept.</p><![foo[ junk ]]><p>Lost.</p>", URL)

    assert page.markdown == "Kept."


def test_a_page_with_no_title_has_none() -> None:
    assert parse_page("<p>x</p>", URL).title is None
