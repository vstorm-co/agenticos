"""The SharePoint and OneDrive connector against a fake Microsoft 365 tenant (#985).

`_Tenant` answers the Entra token endpoint, the Graph calls the connector makes
and the SharePoint download host, from an in-memory library - below the HTTP
client, so every header, host and retry is the connector's own. Throttling,
refusals and outages are queued per path, which is how a test decides what
Graph answers next.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, unquote

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import settings
from app.core.exceptions import BadRequestError, ExternalServiceError
from app.core.secret_kinds import ApiKeySecret, EntraAppSecret
from app.services.rag.connectors import CONNECTOR_REGISTRY, RemoteFile, WithdrawnFile
from app.services.rag.connectors.sharepoint import GRAPH, SharePointConfig, SharePointConnector

pytestmark = pytest.mark.anyio

SITE = "https://contoso.sharepoint.com/sites/Handbook"
SITE_ID = "contoso.sharepoint.com,11111111-aaaa,22222222-bbbb"
DRIVE = "b!docs-drive"
SECRET = "super-secret-value-123"
CREDENTIAL = EntraAppSecret(
    tenant_id="contoso.onmicrosoft.com",
    client_id="0f9e8d7c-6b5a-4f3e-9d2c-1b0a9f8e7d6c",
    client_secret=SECRET,
)


@dataclass
class _Node:
    name: str
    parent: str | None
    content: bytes | None = None  # None for a folder
    package: bool = False
    size: int | None = None

    @property
    def is_folder(self) -> bool:
        return self.content is None and not self.package


@dataclass
class _Tenant:
    """One site, its libraries, and a record of every request made to any host."""

    nodes: dict[str, _Node] = field(default_factory=lambda: {"root": _Node("root", None)})
    libraries: dict[str, str] = field(
        default_factory=lambda: {"Documents": DRIVE, "Policies": "b!policies"}
    )
    requests: list[httpx.Request] = field(default_factory=list)
    queued: dict[str, list[httpx.Response | Exception]] = field(default_factory=dict)
    page_size: int = 100
    cursor: int = 0
    changed_at: dict[str, int] = field(default_factory=dict)
    expired_links: set[int] = field(default_factory=set)
    download_host: str = "contoso.sharepoint.com"
    token_expires_in: int = 3600
    tokens_issued: int = 0

    def add(
        self,
        item_id: str,
        name: str,
        *,
        parent: str = "root",
        content: bytes | None = None,
        package: bool = False,
    ) -> None:
        self.nodes[item_id] = _Node(name, parent, content, package=package)
        self.touch(item_id)

    def touch(self, item_id: str) -> None:
        self.cursor += 1
        self.changed_at[item_id] = self.cursor

    def delete(self, item_id: str) -> None:
        del self.nodes[item_id]
        self.touch(item_id)

    def queue(self, path: str, *answers: httpx.Response | Exception) -> None:
        self.queued.setdefault(path, []).extend(answers)

    def graph_requests(self, path: str) -> list[httpx.Request]:
        return [
            r for r in self.requests if r.url.host == "graph.microsoft.com" and r.url.path == path
        ]

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = unquote(request.url.path)
        pending = self.queued.get(path)
        if pending:
            answer = pending.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer
        if request.url.host == "login.microsoftonline.com":
            self.tokens_issued += 1
            return httpx.Response(
                200,
                json={
                    "access_token": f"graph-token-{self.tokens_issued}",
                    "expires_in": self.token_expires_in,
                },
            )
        if request.url.host == self.download_host:
            item_id = parse_qs(request.url.query.decode())["id"][0]
            node = self.nodes.get(item_id)
            return (
                httpx.Response(404) if node is None else httpx.Response(200, content=node.content)
            )
        return self._graph(request, path)

    def _graph(self, request: httpx.Request, path: str) -> httpx.Response:
        assert request.headers["authorization"].startswith("Bearer graph-token-")
        route = path.removeprefix("/v1.0/")
        if route == "sites/contoso.sharepoint.com:/sites/Handbook":
            return httpx.Response(200, json={"id": SITE_ID})
        if route == f"sites/{SITE_ID}/drive":
            return httpx.Response(200, json={"id": DRIVE, "name": "Documents"})
        if route == f"sites/{SITE_ID}/drives":
            return httpx.Response(
                200, json={"value": [{"id": i, "name": n} for n, i in self.libraries.items()]}
            )
        if route.startswith(f"drives/{DRIVE}/"):
            return self._drive(request, route.removeprefix(f"drives/{DRIVE}/"))
        return httpx.Response(404, json={"error": {"code": "itemNotFound", "message": "not here"}})

    def _drive(self, request: httpx.Request, route: str) -> httpx.Response:
        query = parse_qs(request.url.query.decode())
        if route == "root/delta":
            return self._delta(query["token"][0])
        if route == "root":
            return httpx.Response(200, json=self._item("root"))
        if route.startswith("root:/"):
            found = self._by_path(route.removeprefix("root:/"))
            return (
                httpx.Response(404)
                if found is None
                else httpx.Response(200, json=self._item(found))
            )
        parts = route.split("/")  # items/{id} or items/{id}/children
        item_id = parts[1]
        if item_id not in self.nodes:
            return httpx.Response(404, json={"error": {"code": "itemNotFound"}})
        if len(parts) == 2:
            return httpx.Response(200, json=self._item(item_id))
        children = [self._item(i) for i, n in self.nodes.items() if n.parent == item_id]
        start = int(query.get("skip", ["0"])[0])
        page: dict[str, object] = {"value": children[start : start + self.page_size]}
        if start + self.page_size < len(children):
            page["@odata.nextLink"] = (
                f"{GRAPH}/drives/{DRIVE}/items/{item_id}/children?skip={start + self.page_size}"
            )
        return httpx.Response(200, json=page)

    def _delta(self, token: str) -> httpx.Response:
        link = f"{GRAPH}/drives/{DRIVE}/root/delta?token=T{self.cursor}"
        if token == "latest":
            return httpx.Response(200, json={"value": [], "@odata.deltaLink": link})
        since = int(token.removeprefix("T"))
        if since in self.expired_links:
            return httpx.Response(410, json={"error": {"code": "resyncRequired"}})
        changed = [{"id": i} for i, at in self.changed_at.items() if at > since]
        # Graph reports the root folder alongside whatever changed below it.
        value = [{"id": "root", "root": {}}, *changed] if changed else []
        return httpx.Response(200, json={"value": value, "@odata.deltaLink": link})

    def _by_path(self, path: str) -> str | None:
        current = "root"
        for segment in path.split("/"):
            match = [i for i, n in self.nodes.items() if n.parent == current and n.name == segment]
            if not match:
                return None
            current = match[0]
        return current

    def _item(self, item_id: str) -> dict[str, object]:
        node = self.nodes[item_id]
        body: dict[str, object] = {
            "id": item_id,
            "name": node.name,
            "lastModifiedDateTime": "2026-09-20T10:00:00Z",
        }
        if item_id == "root":
            body["root"] = {}
        if node.is_folder:
            body["folder"] = {"childCount": 0}
        elif node.package:
            body["package"] = {"type": "oneNote"}
        else:
            assert node.content is not None
            body["size"] = node.size if node.size is not None else len(node.content)
            body["file"] = {"mimeType": "application/octet-stream"}
            body["@microsoft.graph.downloadUrl"] = (
                f"https://{self.download_host}/_layouts/15/download.aspx?id={item_id}&tempauth=abc"
            )
        return body


class _Fast(SharePointConnector):
    RETRY_BACKOFF = 0.0


def _connector(tenant: _Tenant) -> SharePointConnector:
    return _Fast(transport=httpx.MockTransport(tenant.handler))


def _handbook() -> _Tenant:
    tenant = _Tenant()
    tenant.add("f-hr", "HR")
    tenant.add("f-it", "IT")
    tenant.add("f-leave", "Leave", parent="f-hr")
    tenant.add("i-welcome", "Welcome.md", content=b"# Welcome")
    tenant.add("i-photo", "team.png", content=b"\x89PNG")
    tenant.add("i-notes", "Notebook", package=True)
    tenant.add("i-hr", "Handbook.pdf", parent="f-hr", content=b"%PDF-1.7 hr")
    tenant.add("i-leave", "leave.DOCX", parent="f-leave", content=b"docx bytes")
    tenant.add("i-it", "laptops.txt", parent="f-it", content=b"laptops")
    return tenant


def _names(files: list[RemoteFile]) -> set[str]:
    return {f.name for f in files}


class TestTheConfig:
    @pytest.mark.parametrize(
        ("site_url", "expected"),
        [
            ("https://contoso.sharepoint.com/sites/Handbook/", SITE),
            ("https://CONTOSO.sharepoint.com/sites/Handbook", SITE),
            ("https://contoso.sharepoint.com", "https://contoso.sharepoint.com"),
            (
                "https://contoso-my.sharepoint.com/personal/jane_contoso_com",
                "https://contoso-my.sharepoint.com/personal/jane_contoso_com",
            ),
        ],
    )
    def test_a_site_or_a_onedrive_is_spelled_one_way(self, site_url: str, expected: str) -> None:
        assert SharePointConfig(site_url=site_url).site_url == expected

    def test_graph_addresses_the_site_by_host_and_path(self) -> None:
        assert (
            SharePointConfig(site_url=SITE).site_address()
            == "sites/contoso.sharepoint.com:/sites/Handbook"
        )
        root = SharePointConfig(site_url="https://contoso.sharepoint.com")
        assert root.site_address() == "sites/contoso.sharepoint.com"

    @pytest.mark.parametrize(
        ("site_url", "says"),
        [
            ("http://contoso.sharepoint.com/sites/Handbook", "https://"),
            ("https://intranet.contoso.com/sites/Handbook", "sharepoint.com host"),
            ("https://contoso.sharepoint.com.evil.test/sites/x", "sharepoint.com host"),
            ("https://contoso.sharepoint.com:8443/sites/Handbook", "no port"),
            ("https://contoso.sharepoint.com:99999/sites/Handbook", "no port"),
            ("https://user@contoso.sharepoint.com/sites/Handbook", "user name"),
            ("https://contoso.sharepoint.com/sites/Handbook?web=1", "query string"),
            (
                "https://contoso.sharepoint.com/sites/Handbook/Shared%20Documents",
                "not a site's address",
            ),
            (
                "https://contoso.sharepoint.com/sites/Handbook/SitePages/Home.aspx",
                "not a site's address",
            ),
        ],
    )
    async def test_anything_but_a_site_address_is_refused_on_the_field(
        self, site_url: str, says: str
    ) -> None:
        refusal = await SharePointConnector().validate_config({"site_url": site_url})

        assert refusal is not None
        assert refusal.field == "site_url"
        assert says in refusal.message

    async def test_the_site_url_is_the_one_required_field(self) -> None:
        refusal = await SharePointConnector().validate_config({})

        assert refusal is not None
        assert (refusal.field, refusal.message) == ("site_url", "Missing required field: Site URL")

    async def test_a_valid_config_is_accepted(self) -> None:
        assert (
            await SharePointConnector().validate_config({"site_url": SITE, "folder_path": "HR"})
            is None
        )

    def test_a_folder_is_spelled_with_single_slashes(self) -> None:
        config = SharePointConfig(site_url=SITE, folder_path=" /Policies// HR /")

        assert config.folder_path == "Policies/HR"
        assert SharePointConfig(site_url=SITE, folder_path=" / ").folder_path is None

    @pytest.mark.parametrize("folder", ["../other", "HR/./x", "a:b", "what?", "tab\there"])
    async def test_a_folder_sharepoint_could_not_hold_is_refused(self, folder: str) -> None:
        refusal = await SharePointConnector().validate_config(
            {"site_url": SITE, "folder_path": folder}
        )

        assert refusal is not None
        assert refusal.field == "folder_path"

    def test_a_library_is_a_name_or_nothing(self) -> None:
        assert SharePointConfig(site_url=SITE, library=" Policies ").library == "Policies"
        assert SharePointConfig(site_url=SITE, library="  ").library is None
        for bad in ("Shared/Documents", "x" * 256, "a|b"):
            with pytest.raises(ValidationError, match="document library"):
                SharePointConfig(site_url=SITE, library=bad)

    def test_extensions_are_normalised_and_deduplicated(self) -> None:
        config = SharePointConfig(site_url=SITE, extensions=["PDF", ".pdf", " md ", ""])

        assert config.extensions == [".pdf", ".md"]
        assert SharePointConfig(site_url=SITE).extensions == [".pdf", ".docx", ".md", ".txt"]

    @pytest.mark.parametrize(
        ("extensions", "says"), [(["*.pdf"], "not a file extension"), ([" "], "At least one")]
    )
    async def test_extensions_that_match_nothing_are_refused(
        self, extensions: list[str], says: str
    ) -> None:
        refusal = await SharePointConnector().validate_config(
            {"site_url": SITE, "extensions": extensions}
        )

        assert refusal is not None
        assert refusal.field == "extensions"
        assert says in refusal.message

    def test_it_is_registered_and_asks_for_an_entra_app(self) -> None:
        assert CONNECTOR_REGISTRY["sharepoint"] is SharePointConnector
        assert SharePointConnector.SECRET_KIND.value == "entra_app"


@pytest.mark.security
class TestTheCredential:
    def test_the_hint_is_the_public_client_id(self) -> None:
        assert CREDENTIAL.hint == "7d6c"
        assert SECRET not in repr(CREDENTIAL)

    @pytest.mark.parametrize(
        "changes",
        [
            {"tenant_id": "contoso/../evil"},
            {"tenant_id": "-leading"},
            {"client_id": "not-a-guid"},
            {"client_secret": "short"},
        ],
    )
    def test_a_malformed_app_registration_is_refused_at_paste_time(
        self, changes: dict[str, str]
    ) -> None:
        fields = {
            "tenant_id": CREDENTIAL.tenant_id,
            "client_id": CREDENTIAL.client_id,
            "client_secret": SECRET,
            **changes,
        }
        with pytest.raises(ValidationError):
            EntraAppSecret.model_validate(fields)

    async def test_a_source_with_no_credential_is_refused(self) -> None:
        with pytest.raises(BadRequestError, match="has no credential"):
            await SharePointConnector().list_files({"site_url": SITE}, None)

    async def test_another_kind_of_secret_is_refused(self) -> None:
        with pytest.raises(BadRequestError, match="needs a Microsoft Entra app"):
            await SharePointConnector().list_files(
                {"site_url": SITE}, ApiKeySecret(api_key="sk-12345678")
            )

    async def test_the_secret_goes_only_to_entra_and_the_token_only_to_graph(
        self, tmp_path: Path
    ) -> None:
        tenant = _handbook()
        connector = _connector(tenant)

        listing = await connector.list_files({"site_url": SITE}, CREDENTIAL)
        welcome = next(f for f in listing.files if f.name == "Welcome.md")
        await connector.download_file(
            welcome, tmp_path, config={"site_url": SITE}, credential=CREDENTIAL
        )

        sign_in = [r for r in tenant.requests if r.url.host == "login.microsoftonline.com"]
        assert len(sign_in) == 1, "one token serves the whole sync"
        assert sign_in[0].url.path == "/contoso.onmicrosoft.com/oauth2/v2.0/token"
        form = parse_qs(sign_in[0].content.decode())
        assert form["grant_type"] == ["client_credentials"]
        assert form["scope"] == ["https://graph.microsoft.com/.default"]
        assert form["client_secret"] == [SECRET]
        others = [r for r in tenant.requests if r not in sign_in]
        assert all(SECRET.encode() not in r.content and SECRET not in str(r.url) for r in others)
        downloads = [r for r in tenant.requests if r.url.host == "contoso.sharepoint.com"]
        assert downloads
        assert all("authorization" not in r.headers for r in downloads)

    async def test_a_token_about_to_expire_is_renewed(self) -> None:
        tenant = _handbook()
        tenant.token_expires_in = 60  # inside the renewal margin: every request signs in again

        await _connector(tenant).list_files({"site_url": SITE}, CREDENTIAL)

        assert tenant.tokens_issued > 1

    @pytest.mark.parametrize(
        ("status", "code"), [(401, "invalid_client"), (400, "unauthorized_client")]
    )
    async def test_a_refused_sign_in_names_the_code_and_not_the_secret(
        self, status: int, code: str
    ) -> None:
        tenant = _handbook()
        tenant.queue(
            "/contoso.onmicrosoft.com/oauth2/v2.0/token",
            httpx.Response(
                status, json={"error": code, "error_description": f"AADSTS7000215 {SECRET}"}
            ),
        )

        with pytest.raises(BadRequestError) as refused:
            await _connector(tenant).list_files({"site_url": SITE}, CREDENTIAL)

        assert code in refused.value.message
        assert "expired" in refused.value.message
        assert SECRET not in refused.value.message
        assert len(tenant.requests) == 1, "a refusal is not retried"

    async def test_a_sign_in_with_no_readable_code_says_the_status(self) -> None:
        tenant = _handbook()
        tenant.queue(
            "/contoso.onmicrosoft.com/oauth2/v2.0/token",
            httpx.Response(401, text="<html>no</html>"),
        )

        with pytest.raises(BadRequestError, match=r"\(HTTP 401\)"):
            await _connector(tenant).list_files({"site_url": SITE}, CREDENTIAL)

    @pytest.mark.parametrize(
        ("answer", "says"),
        [
            (httpx.Response(302, headers={"location": "https://elsewhere.test/"}), "HTTP 302"),
            (httpx.Response(200, json={"token_type": "Bearer"}), "no usable token"),
        ],
    )
    async def test_a_sign_in_that_yields_no_token_is_an_upstream_failure(
        self, answer: httpx.Response, says: str
    ) -> None:
        tenant = _handbook()
        tenant.queue("/contoso.onmicrosoft.com/oauth2/v2.0/token", answer)

        with pytest.raises(ExternalServiceError, match=says):
            await _connector(tenant).list_files({"site_url": SITE}, CREDENTIAL)


class TestTheListing:
    async def test_the_asked_for_types_are_listed_from_every_folder(self) -> None:
        listing = await _connector(_handbook()).list_files({"site_url": SITE}, CREDENTIAL)

        assert listing.complete
        assert listing.problems == []
        assert _names(listing.files) == {"Welcome.md", "Handbook.pdf", "leave.DOCX", "laptops.txt"}
        handbook = next(f for f in listing.files if f.name == "Handbook.pdf")
        assert handbook.source_path == f"sharepoint://{DRIVE}/i-hr"
        assert (handbook.id, handbook.size, handbook.mime_type) == (
            "i-hr",
            11,
            "application/octet-stream",
        )
        assert handbook.modified_at is not None

    async def test_subfolders_can_be_left_out(self) -> None:
        listing = await _connector(_handbook()).list_files(
            {"site_url": SITE, "include_subfolders": False}, CREDENTIAL
        )

        assert _names(listing.files) == {"Welcome.md"}

    async def test_a_folder_narrows_the_listing(self) -> None:
        listing = await _connector(_handbook()).list_files(
            {"site_url": SITE, "folder_path": "HR"}, CREDENTIAL
        )

        assert _names(listing.files) == {"Handbook.pdf", "leave.DOCX"}

    async def test_the_types_can_be_widened(self) -> None:
        listing = await _connector(_handbook()).list_files(
            {"site_url": SITE, "extensions": [".png"], "include_subfolders": False}, CREDENTIAL
        )

        assert _names(listing.files) == {"team.png"}

    @pytest.mark.parametrize(
        ("folder", "says"), [("Missing", "has no folder 'Missing'"), ("Welcome.md", "is a file")]
    )
    async def test_a_folder_that_is_not_one_is_refused(self, folder: str, says: str) -> None:
        with pytest.raises(BadRequestError, match=says):
            await _connector(_handbook()).list_files(
                {"site_url": SITE, "folder_path": folder}, CREDENTIAL
            )

    async def test_a_library_is_found_by_name_whatever_its_case(self) -> None:
        tenant = _handbook()

        await _connector(tenant).list_files({"site_url": SITE, "library": "documents"}, CREDENTIAL)

        assert tenant.graph_requests(f"/v1.0/sites/{SITE_ID}/drives")
        assert not tenant.graph_requests(f"/v1.0/sites/{SITE_ID}/drive")

    async def test_a_library_that_is_not_there_names_the_ones_that_are(self) -> None:
        with pytest.raises(
            BadRequestError, match=r"named 'Wiki'\. Its libraries are: Documents, Policies"
        ):
            await _connector(_handbook()).list_files(
                {"site_url": SITE, "library": "Wiki"}, CREDENTIAL
            )

    async def test_a_site_the_app_cannot_see_says_sites_selected_may_be_why(self) -> None:
        with pytest.raises(BadRequestError, match=r"Sites\.Selected"):
            await _connector(_handbook()).list_files(
                {"site_url": "https://contoso.sharepoint.com/sites/Other"}, CREDENTIAL
            )

    async def test_the_drive_is_looked_up_once_per_sync(self) -> None:
        tenant = _handbook()
        connector = _connector(tenant)

        await connector.remote_version({"site_url": SITE}, CREDENTIAL, None)
        await connector.list_files({"site_url": SITE}, CREDENTIAL)

        assert len(tenant.graph_requests("/v1.0/sites/contoso.sharepoint.com:/sites/Handbook")) == 1

    async def test_every_page_of_a_folder_is_read(self) -> None:
        tenant = _handbook()
        for number in range(5):
            tenant.add(f"i-extra-{number}", f"extra-{number}.md", content=b"x")
        tenant.page_size = 2

        listing = await _connector(tenant).list_files(
            {"site_url": SITE, "include_subfolders": False}, CREDENTIAL
        )

        assert len(listing.files) == 6

    async def test_a_next_link_off_graph_is_not_followed(self) -> None:
        tenant = _handbook()
        tenant.queue(
            f"/v1.0/drives/{DRIVE}/items/root/children",
            httpx.Response(
                200, json={"value": [], "@odata.nextLink": "https://attacker.test/next"}
            ),
        )

        with pytest.raises(ExternalServiceError, match="link to another host"):
            await _connector(tenant).list_files({"site_url": SITE}, CREDENTIAL)
        assert all(r.url.host != "attacker.test" for r in tenant.requests)

    async def test_a_subfolder_that_cannot_be_read_makes_the_listing_partial(self) -> None:
        """Its files are unknown this run, so the sync must not remove their documents."""
        tenant = _handbook()
        tenant.queue(
            f"/v1.0/drives/{DRIVE}/items/f-hr/children",
            httpx.Response(403, json={"error": {"code": "accessDenied"}}),
        )

        listing = await _connector(tenant).list_files({"site_url": SITE}, CREDENTIAL)

        assert not listing.complete
        assert _names(listing.files) == {"Welcome.md", "laptops.txt"}
        assert len(listing.problems) == 1
        assert listing.problems[0].startswith("The folder HR could not be listed: ")
        assert "accessDenied" in listing.problems[0]

    async def test_the_configured_folder_refused_fails_the_listing(self) -> None:
        tenant = _handbook()
        tenant.queue(f"/v1.0/drives/{DRIVE}/items/root/children", httpx.Response(401))

        with pytest.raises(BadRequestError, match="did not accept the app's token"):
            await _connector(tenant).list_files({"site_url": SITE}, CREDENTIAL)

    @pytest.mark.parametrize(
        ("answer", "says"),
        [
            (
                httpx.Response(
                    200, json={"value": [{"id": "bad id/../x", "name": "x", "folder": {}}]}
                ),
                "id",
            ),
            (httpx.Response(200, text="not json"), "could not read"),
            (httpx.Response(200, json={"value": "not a list"}), "could not read"),
            (httpx.Response(200, json={"id": "root", "name": "root"}), "with an item, not a list"),
            (
                httpx.Response(418, json={"error": {"code": "teapot"}}),
                r"HTTP 418 for the folder .* \(teapot\)",
            ),
        ],
    )
    async def test_an_answer_graph_should_not_give_is_an_upstream_failure(
        self, answer: httpx.Response, says: str
    ) -> None:
        tenant = _handbook()
        tenant.queue(f"/v1.0/drives/{DRIVE}/items/root/children", answer)

        with pytest.raises(ExternalServiceError, match=says):
            await _connector(tenant).list_files({"site_url": SITE}, CREDENTIAL)

    async def test_a_list_where_an_item_belongs_is_an_upstream_failure(self) -> None:
        tenant = _handbook()
        tenant.queue(f"/v1.0/drives/{DRIVE}/root", httpx.Response(200, json={"value": []}))

        with pytest.raises(ExternalServiceError, match="with a list, not an item"):
            await _connector(tenant).list_files({"site_url": SITE}, CREDENTIAL)


class TestRetries:
    async def test_throttling_is_waited_out_as_graph_asks(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        slept: list[float] = []

        async def sleep(seconds: float) -> None:
            slept.append(seconds)

        monkeypatch.setattr("app.services.rag.connectors.sharepoint.asyncio.sleep", sleep)
        tenant = _handbook()
        tenant.queue(
            f"/v1.0/drives/{DRIVE}/items/root/children",
            httpx.Response(429, headers={"retry-after": "7"}),
            httpx.Response(503, headers={"retry-after": "3600"}),
            httpx.Response(503),
        )

        listing = await SharePointConnector(
            transport=httpx.MockTransport(tenant.handler)
        ).list_files({"site_url": SITE}, CREDENTIAL)

        assert listing.complete
        assert slept == [7.0, 60.0, 4.0], "Retry-After, capped, else the doubling backoff"

    async def test_an_outage_that_outlasts_the_attempts_fails_loudly(self) -> None:
        tenant = _handbook()
        tenant.queue(f"/v1.0/drives/{DRIVE}/items/root/children", *[httpx.Response(503)] * 4)

        with pytest.raises(ExternalServiceError, match="after 4 attempts"):
            await _connector(tenant).list_files({"site_url": SITE}, CREDENTIAL)

    async def test_a_dropped_connection_is_retried_then_named(self) -> None:
        tenant = _handbook()
        tenant.queue(f"/v1.0/drives/{DRIVE}/items/root/children", httpx.ConnectError("reset"))

        listing = await _connector(tenant).list_files({"site_url": SITE}, CREDENTIAL)
        assert listing.complete

        tenant.queue(
            f"/v1.0/drives/{DRIVE}/items/root/children", *[httpx.ConnectError("reset")] * 4
        )
        with pytest.raises(ExternalServiceError, match=r"could not be reached .*\(ConnectError\)"):
            await _connector(tenant).list_files({"site_url": SITE}, CREDENTIAL)

    async def test_a_sign_in_outage_is_retried(self) -> None:
        tenant = _handbook()
        tenant.queue("/contoso.onmicrosoft.com/oauth2/v2.0/token", httpx.Response(503))

        listing = await _connector(tenant).list_files({"site_url": SITE}, CREDENTIAL)

        assert listing.complete
        assert tenant.tokens_issued == 1


class TestDownloads:
    async def _file(self, tenant: _Tenant, name: str) -> tuple[SharePointConnector, RemoteFile]:
        connector = _connector(tenant)
        listing = await connector.list_files({"site_url": SITE}, CREDENTIAL)
        return connector, next(f for f in listing.files if f.name == name)

    async def test_a_file_is_written_where_the_base_class_says(self, tmp_path: Path) -> None:
        connector, handbook = await self._file(_handbook(), "Handbook.pdf")

        path = await connector.download_file(handbook, tmp_path, credential=CREDENTIAL)

        assert path == tmp_path / "Handbook.pdf"
        assert path.read_bytes() == b"%PDF-1.7 hr"

    async def test_a_file_deleted_since_the_listing_is_withdrawn_not_failed(
        self, tmp_path: Path
    ) -> None:
        tenant = _handbook()
        connector, handbook = await self._file(tenant, "Handbook.pdf")
        tenant.delete("i-hr")

        with pytest.raises(WithdrawnFile, match="deleted from the library"):
            await connector.download_file(handbook, tmp_path, credential=CREDENTIAL)

    async def test_an_item_with_nothing_to_download_is_withdrawn(self, tmp_path: Path) -> None:
        tenant = _handbook()
        connector, handbook = await self._file(tenant, "Handbook.pdf")
        tenant.queue(
            f"/v1.0/drives/{DRIVE}/items/i-hr",
            httpx.Response(200, json={"id": "i-hr", "folder": {}}),
        )

        with pytest.raises(WithdrawnFile, match="no longer a file"):
            await connector.download_file(handbook, tmp_path, credential=CREDENTIAL)

    async def test_a_file_over_the_cap_is_refused_before_it_is_downloaded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 1)
        tenant = _handbook()
        tenant.nodes["i-hr"].size = 3 * 1024 * 1024
        connector, handbook = await self._file(tenant, "Handbook.pdf")

        with pytest.raises(BadRequestError, match="is 3 MB, and a synced file may be at most 1 MB"):
            await connector.download_file(handbook, tmp_path, credential=CREDENTIAL)
        assert not [r for r in tenant.requests if r.url.host == "contoso.sharepoint.com"]

    async def test_a_body_larger_than_its_size_said_is_cut_off(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 1)
        tenant = _handbook()
        tenant.nodes["i-hr"].content = b"x" * (1024 * 1024 + 1)
        tenant.nodes["i-hr"].size = 10
        connector, handbook = await self._file(tenant, "Handbook.pdf")

        with pytest.raises(BadRequestError, match="larger than the 1 MB"):
            await connector.download_file(handbook, tmp_path, credential=CREDENTIAL)

    async def test_a_download_url_outside_sharepoint_is_not_fetched(self, tmp_path: Path) -> None:
        tenant = _handbook()
        connector, handbook = await self._file(tenant, "Handbook.pdf")
        tenant.download_host = "attacker.test"

        with pytest.raises(ExternalServiceError, match="outside SharePoint"):
            await connector.download_file(handbook, tmp_path, credential=CREDENTIAL)
        assert all(r.url.host != "attacker.test" for r in tenant.requests)

    async def test_a_redirect_is_followed_only_within_sharepoint(self, tmp_path: Path) -> None:
        tenant = _handbook()
        connector, handbook = await self._file(tenant, "Handbook.pdf")
        moved = "https://contoso.sharepoint.com/_layouts/15/download.aspx?id=i-hr&hop=2"
        tenant.queue("/_layouts/15/download.aspx", httpx.Response(302, headers={"location": moved}))

        path = await connector.download_file(handbook, tmp_path, credential=CREDENTIAL)
        assert path.read_bytes() == b"%PDF-1.7 hr"

        tenant.queue(
            "/_layouts/15/download.aspx",
            httpx.Response(302, headers={"location": "https://attacker.test/x"}),
        )
        with pytest.raises(ExternalServiceError, match="outside SharePoint"):
            await connector.download_file(handbook, tmp_path, credential=CREDENTIAL)

    async def test_a_relative_redirect_is_resolved_against_sharepoint(self, tmp_path: Path) -> None:
        tenant = _handbook()
        connector, handbook = await self._file(tenant, "Handbook.pdf")
        tenant.queue(
            "/_layouts/15/download.aspx",
            httpx.Response(302, headers={"location": "/_layouts/15/download.aspx?id=i-hr&hop=2"}),
        )

        path = await connector.download_file(handbook, tmp_path, credential=CREDENTIAL)

        assert path.read_bytes() == b"%PDF-1.7 hr"
        assert str(tenant.requests[-1].url).startswith("https://contoso.sharepoint.com/_layouts/")

    async def test_a_redirect_loop_ends(self, tmp_path: Path) -> None:
        tenant = _handbook()
        connector, handbook = await self._file(tenant, "Handbook.pdf")
        loop = "https://contoso.sharepoint.com/_layouts/15/download.aspx?id=i-hr"
        tenant.queue(
            "/_layouts/15/download.aspx", *[httpx.Response(302, headers={"location": loop})] * 4
        )

        with pytest.raises(ExternalServiceError, match="too many times"):
            await connector.download_file(handbook, tmp_path, credential=CREDENTIAL)

    @pytest.mark.parametrize("answer", [httpx.Response(403), httpx.Response(302)])
    async def test_a_download_refused_is_a_failed_file(
        self, tmp_path: Path, answer: httpx.Response
    ) -> None:
        tenant = _handbook()
        connector, handbook = await self._file(tenant, "Handbook.pdf")
        tenant.queue("/_layouts/15/download.aspx", answer)

        with pytest.raises(
            ExternalServiceError, match=f"HTTP {answer.status_code} when Handbook.pdf"
        ):
            await connector.download_file(handbook, tmp_path, credential=CREDENTIAL)

    async def test_a_throttled_download_is_retried(self, tmp_path: Path) -> None:
        tenant = _handbook()
        connector, handbook = await self._file(tenant, "Handbook.pdf")
        tenant.queue(
            "/_layouts/15/download.aspx", httpx.Response(503, headers={"retry-after": "0"})
        )

        path = await connector.download_file(handbook, tmp_path, credential=CREDENTIAL)

        assert path.read_bytes() == b"%PDF-1.7 hr"


def _fresh_links(tenant: _Tenant) -> list[httpx.Request]:
    """The requests that took the change feed where it stands, rather than asking what changed."""
    feed = tenant.graph_requests(f"/v1.0/drives/{DRIVE}/root/delta")
    return [r for r in feed if r.url.params.get("token") == "latest"]


class TestTheChangeFeed:
    async def _version(
        self, tenant: _Tenant, previous: str | None, config: dict[str, object] | None = None
    ) -> str:
        return await _connector(tenant).remote_version(
            config or {"site_url": SITE}, CREDENTIAL, previous
        )

    async def test_a_first_run_takes_the_feed_where_it_stands(self) -> None:
        tenant = _handbook()

        version = await self._version(tenant, None)

        assert version == f"{DRIVE} {GRAPH}/drives/{DRIVE}/root/delta?token=T{tenant.cursor}"

    async def test_nothing_changed_answers_the_previous_version_back(self) -> None:
        tenant = _handbook()
        first = await self._version(tenant, None)

        assert await self._version(tenant, first) == first
        assert len(_fresh_links(tenant)) == 1, "an unchanged feed is not read again from the top"

    async def test_a_change_anywhere_in_the_library_moves_the_version(self) -> None:
        """Delta items carry no path, so a change outside the folder counts too."""
        tenant = _handbook()
        first = await self._version(tenant, None, {"site_url": SITE, "folder_path": "HR"})
        tenant.touch("i-it")

        second = await self._version(tenant, first, {"site_url": SITE, "folder_path": "HR"})

        assert second != first
        assert second.endswith(f"token=T{tenant.cursor}")

    async def test_a_link_graph_no_longer_honours_is_replaced(self) -> None:
        tenant = _handbook()
        first = await self._version(tenant, None)
        tenant.expired_links.add(tenant.cursor)

        await self._version(tenant, first)

        assert len(_fresh_links(tenant)) == 2

    async def test_another_drives_version_is_not_asked_about(self) -> None:
        tenant = _handbook()
        stale = f"b!another-drive {GRAPH}/drives/b!another-drive/root/delta?token=T0"

        version = await self._version(tenant, stale)

        assert version.startswith(f"{DRIVE} ")
        assert not tenant.graph_requests("/v1.0/drives/b!another-drive/root/delta")

    async def test_a_stored_link_off_graph_is_never_followed(self) -> None:
        tenant = _handbook()

        version = await self._version(tenant, f"{DRIVE} https://attacker.test/delta")

        assert version.startswith(f"{DRIVE} {GRAPH}")
        assert all(r.url.host != "attacker.test" for r in tenant.requests)

    async def test_a_feed_that_ends_without_a_link_is_an_upstream_failure(self) -> None:
        tenant = _handbook()
        tenant.queue(f"/v1.0/drives/{DRIVE}/root/delta", httpx.Response(200, json={"value": []}))

        with pytest.raises(ExternalServiceError, match="without a delta link"):
            await self._version(tenant, None)


class TestCleanup:
    async def test_the_session_is_closed_once_and_closing_again_is_harmless(self) -> None:
        tenant = _handbook()
        connector = _connector(tenant)
        await connector.list_files({"site_url": SITE}, CREDENTIAL)

        await connector.aclose()
        await connector.aclose()
        await SharePointConnector().aclose()

        # A closed session is replaced, not reused, by the next call.
        listing = await connector.list_files({"site_url": SITE}, CREDENTIAL)
        assert listing.complete
