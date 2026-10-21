"""What a saved browser sign-in keeps, and how it goes back into a browser (#2129).

The pure half: which site a page is on, which of a browser context's cookies are
part of a sign-in to it, what `Storage.setCookies` is given back, and the script
that restores `localStorage`. The CDP calls around them need a live browser and
were checked against one; the vault and the database are in
`tests/integration/test_browser_sign_ins.py`.
"""

import json
from typing import Any
from uuid import uuid4

import pytest
from pydantic import JsonValue

from app.agents.browser_sign_ins import (
    MAX_COOKIES,
    MAX_STORAGE_ITEMS,
    MAX_STORAGE_VALUE,
    SignIn,
    belongs_to,
    bounded_storage,
    cookie_params,
    cookies_for,
    origin_of,
    restore_script,
    site_of,
    storage_from,
)
from app.db.models.browser_sign_in import BrowserSignIn


def _cookie(domain: str, **fields: JsonValue) -> dict[str, JsonValue]:
    return {"name": "li_at", "value": "v", "domain": domain, "path": "/", **fields}


class TestWhichSite:
    @pytest.mark.parametrize(
        ("url", "site"),
        [
            ("https://www.linkedin.com/feed/", "linkedin.com"),
            ("https://WWW.LinkedIn.com", "linkedin.com"),
            ("https://accounts.google.com/signin", "accounts.google.com"),
            ("http://intranet.local:8080/x", "intranet.local"),
        ],
    )
    def test_a_web_page_is_on_its_host_without_www(self, url: str, site: str):
        assert site_of(url) == site

    @pytest.mark.parametrize("url", [None, "", "about:blank", "file:///etc/passwd", "https://"])
    def test_anything_not_on_the_web_is_on_no_site(self, url: str | None):
        assert site_of(url) is None

    def test_the_origin_keeps_scheme_host_and_port(self):
        assert origin_of("https://app.example.com:8443/a?b=c") == "https://app.example.com:8443"


class TestWhichCookies:
    @pytest.mark.parametrize(
        "domain",
        [
            "linkedin.com",
            ".linkedin.com",  # the parent a `www.` sign-in usually rests on
            "www.linkedin.com",
            ".LinkedIn.com",
        ],
    )
    def test_the_site_its_parent_and_its_children_belong(self, domain: str):
        assert belongs_to(domain, "linkedin.com")

    @pytest.mark.parametrize(
        "domain", ["evil-linkedin.com", "linkedin.com.evil.test", "google.com"]
    )
    def test_a_lookalike_or_another_site_does_not(self, domain: str):
        assert not belongs_to(domain, "linkedin.com")

    def test_a_context_s_cookies_are_narrowed_to_the_site_and_bounded(self):
        """A sign-in through a single sign-on provider leaves that provider's
        cookies in the context too; they are the provider's, not the site's."""
        cookies = [
            _cookie(".linkedin.com"),
            _cookie(".google.com"),
            {"name": "no-domain", "value": "x"},
        ] + [_cookie("www.linkedin.com", name=f"c{i}") for i in range(MAX_COOKIES + 5)]

        kept = cookies_for(cookies, "linkedin.com")

        assert len(kept) == MAX_COOKIES
        assert kept[0]["domain"] == ".linkedin.com"
        assert all(cookie["domain"] != ".google.com" for cookie in kept)


class TestPuttingCookiesBack:
    def test_only_what_sets_a_cookie_goes_back(self):
        [param] = cookie_params(
            [
                _cookie(
                    ".linkedin.com", expires=1_900_000_000.5, size=42, session=False, httpOnly=True
                )
            ]
        )
        assert param == {
            "name": "li_at",
            "value": "v",
            "domain": ".linkedin.com",
            "path": "/",
            "expires": 1_900_000_000.5,
            "httpOnly": True,
        }

    def test_a_session_cookie_goes_back_without_its_expiry(self):
        """Read back as -1, which written would be a cookie that expired in 1970."""
        [param] = cookie_params([_cookie(".linkedin.com", expires=-1, session=True)])
        assert "expires" not in param


class TestStorage:
    def test_the_pages_answer_is_read_as_pairs(self):
        raw = json.dumps([["token", "abc"], ["theme", "dark"]])
        assert storage_from(raw) == {"token": "abc", "theme": "dark"}

    @pytest.mark.parametrize(
        "raw",
        [None, 3, "not json", json.dumps({"a": "b"}), json.dumps([["a"], ["b", 1], "c", [1, "x"]])],
    )
    def test_anything_else_is_nothing(self, raw: Any):
        assert storage_from(raw) == {}

    def test_storage_is_bounded_in_entries_and_in_size(self):
        items = {f"k{i}": "v" for i in range(MAX_STORAGE_ITEMS + 10)}
        items["cache"] = "x" * (MAX_STORAGE_VALUE + 1)

        kept = bounded_storage(items)

        assert len(kept) == MAX_STORAGE_ITEMS
        assert "cache" not in kept

    def test_the_restore_script_fills_only_its_own_origin_and_only_what_is_missing(self):
        script = restore_script(
            [
                SignIn(site="a.test", origin="https://a.test", local_storage={"t": "1"}),
                SignIn(site="b.test", origin="https://b.test"),
            ]
        )
        assert json.dumps({"https://a.test": {"t": "1"}}) in script
        assert "[location.origin]" in script
        assert "localStorage.getItem(k) === null" in script


class TestTheRow:
    def test_its_repr_names_the_site_and_never_the_sealed_state(self):
        """A row lands in logs and tracebacks by its repr; the cookies it holds
        are a signed-in session and must not travel with it."""
        row = BrowserSignIn(
            id=uuid4(), user_id=uuid4(), site="notion.so", sealed_state="v1:sealed-cookies"
        )

        shown = repr(row)

        assert "notion.so" in shown
        assert "sealed-cookies" not in shown
