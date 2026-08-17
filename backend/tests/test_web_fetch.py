"""Tests for reading the page behind a URL.

Two properties carry this capability, and they are the two a rewrite would lose.

The first is the refusal: the URL is chosen by a *model* and dereferenced from
inside the container, so a link-local, loopback or cloud-metadata address must be
refused before a socket is opened, and refused as something the model can recover
from rather than as an answer. Those cases run without a network - every address
here is an IP literal, so nothing resolves and nothing is dialled.

The second is that the configuration reaches the thing that does the fetching.
`method` decides who dereferences the URL, and the domain filters have to reach
both paths - the native tool and the local one - because a filter that only
applies to one lapses the day somebody switches `method`.
"""

import re

import pytest
from pydantic import ValidationError
from pydantic_ai import ModelRetry
from pydantic_ai._run_context import RunContext
from pydantic_ai.capabilities import WebFetch
from pydantic_ai.models.test import TestModel
from pydantic_ai.native_tools import WebFetchTool
from pydantic_ai.tools import Tool
from pydantic_ai.usage import RunUsage

from app.agents.capabilities._registry import CapabilityBinding, build, get
from app.agents.capabilities.web_fetch import WebFetchConfig
from app.agents.capabilities.web_fetch._capability import FETCH_DESCRIPTION
from app.services.agent_registry import DEFAULT_GRANTED_SCOPES

pytestmark = pytest.mark.anyio


def _built(**config: object) -> WebFetch[object]:
    built = build([CapabilityBinding(capability_id="web_fetch", config=config)])
    capability = built[0]
    assert isinstance(capability, WebFetch)
    return capability


def _local_tool(capability: WebFetch[object]) -> Tool[object]:
    """The tool the model is handed when this deployment does the fetching."""
    local = capability.local
    assert isinstance(local, Tool)
    return local


async def _fetch(capability: WebFetch[object], url: str) -> object:
    return await _local_tool(capability).function(url=url)


class TestTheRefusal:
    """What the guard has to stop, and how the model hears about it.

    Each of these is an address a page could name in a redirect or a model could
    invent from an internal hostname it saw in a document, and each one is a read
    of somewhere this container can reach and the public cannot.
    """

    @pytest.mark.parametrize(
        "url",
        [
            "http://169.254.169.254/latest/meta-data/",
            "http://[fd00:ec2::254]/latest/meta-data/",
            "http://100.100.100.200/latest/meta-data/",
            "http://metadata.google.internal/computeMetadata/v1/",
        ],
        ids=["aws-imds", "aws-imds-v6", "alibaba", "gcp-by-name"],
    )
    async def test_a_cloud_metadata_endpoint_is_refused(self, url: str):
        with pytest.raises(ModelRetry):
            await _fetch(_built(), url)

    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1:8000/api/v1/agents",
            "http://localhost:5432/",
            "http://10.0.0.5/",
            "http://192.168.1.1/",
            "http://172.16.0.1/",
        ],
        ids=["loopback", "loopback-by-name", "private-10", "private-192", "private-172"],
    )
    async def test_a_private_or_loopback_address_is_refused(self, url: str):
        with pytest.raises(ModelRetry):
            await _fetch(_built(), url)

    @pytest.mark.parametrize("url", ["file:///etc/passwd", "gopher://example.com/"])
    async def test_a_scheme_that_is_not_http_is_refused(self, url: str):
        with pytest.raises(ModelRetry):
            await _fetch(_built(), url)

    async def test_a_refusal_reaches_the_model_as_something_it_can_recover_from(self):
        """`ModelRetry`, not a returned string and not an unhandled error.

        A refusal shaped like a result is one the model reads as "the page was
        empty" and answers around, and one that escapes the tool call takes the
        whole run down over a URL it could simply have stopped asking for.
        """
        with pytest.raises(ModelRetry, match=re.escape("169.254.169.254")):
            await _fetch(_built(), "http://169.254.169.254/")


class TestWhoFetches:
    """`method` is the whole decision, and all three answers are checked.

    The local tool exists to be the one that behaves identically on every model,
    so it is the default; the other two are what an author picks when the
    provider's own fetch is worth the model lock-in.
    """

    def test_the_default_fetches_through_this_deployment(self):
        assert WebFetchConfig().method == "local"
        capability = _built()
        assert capability.native is False
        assert isinstance(capability.local, Tool)

    async def test_the_default_offers_the_model_one_fetch_tool(self):
        toolset = _built().get_toolset()
        assert toolset is not None
        assert set(await toolset.get_tools(_context())) == {"web_fetch"}

    def test_native_fetch_hands_the_job_to_the_model_provider(self):
        """No request of ours, so no toolset of ours either."""
        capability = _built(method="native")
        assert isinstance(capability.native, WebFetchTool)
        assert capability.local is False
        assert capability.get_toolset() is None

    async def test_auto_offers_ours_only_to_a_model_with_no_native_fetch(self):
        """Both are configured; `unless_native` is what keeps it to one tool.

        Without the marker a model that fetches natively would be offered two
        ways to read a URL, pick between them per call, and produce a
        conversation where half the pages arrived with citations and half did
        not.
        """
        capability = _built(method="auto")
        assert isinstance(capability.native, WebFetchTool)
        toolset = capability.get_toolset()
        assert toolset is not None
        offered = await toolset.get_tools(_context())
        assert [tool.tool_def.unless_native for tool in offered.values()] == [WebFetchTool.kind]


class TestWhatReachesTheFetch:
    """Configuration that does not arrive is configuration that does nothing."""

    def test_the_model_reads_this_repositorys_description_of_the_tool(self):
        """The library ships its own wording, and the Builder shows ours.

        The person choosing what to approve and the model choosing when to call
        should be reading the same sentence - so the declared description is the
        one handed to the tool, and this is what fails if they drift.
        """
        declared = next(tool for tool in get("web_fetch").tools if tool.id == "web_fetch")
        assert declared.description == FETCH_DESCRIPTION
        assert _local_tool(_built()).description == FETCH_DESCRIPTION

    def test_the_content_bound_reaches_the_fetching_tool(self):
        fetcher = _local_tool(_built(max_content_chars=2_000)).function.__self__
        assert fetcher.max_content_length == 2_000

    def test_a_page_is_never_read_into_memory_without_a_ceiling(self):
        """The body is buffered before anything measures it, so an unbounded
        fetch is one tool call able to exhaust the process."""
        fetcher = _local_tool(_built()).function.__self__
        assert fetcher.max_download_bytes is not None
        assert fetcher.allow_local_urls is False

    def test_the_domain_filters_reach_both_the_native_and_the_local_tool(self):
        """The reason they are passed twice. A filter on one path only is a
        filter that lapses when somebody switches `method`."""
        capability = _built(method="auto", allowed_domains=["docs.example.com"])
        assert isinstance(capability.native, WebFetchTool)
        assert capability.native.allowed_domains == ["docs.example.com"]
        assert _local_tool(capability).function.__self__.allowed_domains == ["docs.example.com"]

    def test_a_filter_covers_the_unicode_spelling_of_the_host_it_names(self):
        """The alias a denylist would otherwise have a hole for.

        `urlparse` hands the comparison whatever the URL spelled, and a URL may
        spell a host in Unicode - so `https://exämple.com/` reaches an exact
        match against `xn--exmple-cua.com` and misses. `getaddrinfo` resolves the
        two identically, so the miss is a fetch, not a failure. Both spellings
        are handed to both paths for that reason.
        """
        capability = _built(method="auto", blocked_domains=["exämple.com"])
        assert isinstance(capability.native, WebFetchTool)
        aliases = ["xn--exmple-cua.com", "exämple.com"]
        assert capability.native.blocked_domains == aliases
        assert _local_tool(capability).function.__self__.blocked_domains == aliases

    def test_an_ascii_host_is_passed_once(self):
        """Nothing to alias, so nothing added - the common list stays itself."""
        capability = _built(blocked_domains=["docs.example.com"])
        assert _local_tool(capability).function.__self__.blocked_domains == ["docs.example.com"]

    def test_a_host_that_only_looks_like_an_a_label_is_still_built(self):
        """`xn--a.com` is a hostname somebody may write and punycode cannot
        decode. It has no Unicode alias to add, and refusing to build an agent
        that published cleanly is a worse answer than passing it through."""
        capability = _built(blocked_domains=["xn--a.com"])
        assert _local_tool(capability).function.__self__.blocked_domains == ["xn--a.com"]

    async def test_a_host_outside_the_allowlist_is_refused(self):
        capability = _built(allowed_domains=["docs.example.com"])
        with pytest.raises(ModelRetry):
            await _fetch(capability, "http://93.184.216.34/")

    async def test_a_blocked_host_is_refused(self):
        capability = _built(blocked_domains=["93.184.216.34"])
        with pytest.raises(ModelRetry):
            await _fetch(capability, "http://93.184.216.34/")


class TestTheDomainFilterConfiguration:
    """A filter entry that cannot match is the failure this validator exists for.

    The comparison is on the hostname, exactly, so every shape below matches
    nothing - and matching nothing is invisible in one direction and total in the
    other: a denylist quietly stops denying, an allowlist quietly denies
    everything.
    """

    @pytest.mark.parametrize(
        "domain",
        ["*.example.com", "https://example.com", "example.com/docs", "example.com:8443", ""],
        ids=["wildcard", "scheme", "path", "port", "blank"],
    )
    def test_an_entry_that_could_never_match_is_refused(self, domain: str):
        with pytest.raises(ValidationError, match="bare hostnames"):
            WebFetchConfig(allowed_domains=[domain])

    def test_an_empty_allowlist_is_refused_rather_than_read_as_unrestricted(self):
        """It would allow nothing, which is a tool that refuses every URL."""
        with pytest.raises(ValidationError, match="empty list allows nothing"):
            WebFetchConfig(allowed_domains=[])

    def test_an_empty_denylist_denies_nothing_and_is_read_as_no_denylist(self):
        """The two fields do not mean the same thing by `[]`.

        An empty allowlist allows nothing; an empty denylist blocks nothing,
        which is what `null` already says - so a spec imported from YAML or
        posted by an API client that spells "no denied hosts" as `[]` is saying
        something true and must publish, not be refused with the allowlist's
        error.
        """
        assert WebFetchConfig(blocked_domains=[]).blocked_domains is None

    def test_a_hostname_is_lower_cased_so_it_can_match_at_all(self):
        """The comparison is against what `urlparse` read, which is lower case."""
        assert WebFetchConfig(allowed_domains=[" Docs.Example.COM "]).allowed_domains == [
            "docs.example.com"
        ]

    def test_a_root_label_is_stripped_so_the_entry_can_match(self):
        """`example.com.` and `example.com` are one DNS name.

        The library strips the root label off the requested URL before it
        compares, so an entry that kept one would match nothing at all - and
        being refused outright left an author who copied a name out of a zone
        file with no way to write it.
        """
        assert WebFetchConfig(blocked_domains=["example.com."]).blocked_domains == ["example.com"]

    def test_a_unicode_hostname_is_stored_as_the_name_dns_would_be_asked_for(self):
        """One spelling in the spec, so a stored filter reads the same everywhere."""
        assert WebFetchConfig(blocked_domains=["Exämple.com"]).blocked_domains == [
            "xn--exmple-cua.com"
        ]

    def test_a_hostname_with_no_a_label_is_refused_like_any_other_non_match(self):
        """An empty label has no IDNA encoding, so nothing could ever match it."""
        with pytest.raises(ValidationError, match="bare hostnames"):
            WebFetchConfig(allowed_domains=[".example.com"])

    def test_no_filter_means_no_restriction(self):
        assert WebFetchConfig().allowed_domains is None
        assert WebFetchConfig().blocked_domains is None

    def test_an_explicit_null_is_how_a_stored_spec_says_unrestricted(self):
        """A spec exported to a client's repository writes the field out, so the
        validator is reached with `null` rather than skipped over a default."""
        config = WebFetchConfig(allowed_domains=None, blocked_domains=None)
        assert config.allowed_domains is None
        assert config.blocked_domains is None


class TestHowItIsSwitchedOn:
    def test_fetching_is_its_own_scope(self):
        """Not `web_research`'s `web:read`. Searching reaches one API this
        deployment chose; fetching dereferences whatever a model asks for, so an
        operator can allow the first and refuse the second."""
        assert get("web_fetch").scopes == frozenset({"web:fetch"})
        assert "web:fetch" in DEFAULT_GRANTED_SCOPES

    def test_it_needs_no_credential(self):
        assert get("web_fetch").needs_secret(WebFetchConfig()) is False

    def test_a_binding_with_no_configuration_gets_the_defaults(self):
        assert _built().native is False


def _context() -> RunContext[None]:
    """The least a wrapped toolset needs before it will list its tools."""
    return RunContext(deps=None, model=TestModel(), usage=RunUsage())
