"""A person's saved sign-in to one site, as the web browser carries it (#2129).

A browse starts in a browser context of its own and so signed out of everything,
which is right for a browse nobody in particular asked for and wrong for one a
person asked for in their own chat: "go through my LinkedIn connections" then
needs their password typed in every time. So a person who signs in while they
hold the browser may keep that sign-in, and a later browse acting as them starts
signed in to that site.

What is kept is what a site recognises a signed-in browser by: its cookies, and
the `localStorage` of the origin they signed in on. Both are sealed in the vault
under the person's own scope by `app.services.browser_sign_in`; this module is
the shape and the pure parts - which site a page is on, which cookies belong to
it, and the script that puts the storage back.

**The site is the host without `www.`**, not a registrable domain. Telling
`example.co.uk` from `co.uk` takes the public-suffix list, and nothing else here
needs it. A cookie belongs to a site when its domain is the site, a parent of it
or a child of it - so a sign-in made on `www.linkedin.com` keeps the
`.linkedin.com` cookies it actually depends on.
"""

import json
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, JsonValue

MAX_COOKIES = 300
"""How many cookies one sign-in may keep - a site sets dozens, never hundreds."""

MAX_STORAGE_ITEMS = 200
"""How many `localStorage` entries one sign-in may keep."""

MAX_STORAGE_VALUE = 20_000
"""The longest `localStorage` value kept; a longer one is a cache, not a session."""


class SignIn(BaseModel):
    """What a site needs to see to treat a browser as signed in."""

    model_config = ConfigDict(frozen=True)

    site: str = Field(description="The host signed in to, without `www.`.")
    origin: str = Field(description="The origin whose `localStorage` this holds.")
    cookies: list[dict[str, JsonValue]] = Field(
        default_factory=list,
        description="CDP `Network.Cookie` objects, as `Storage.setCookies` takes them back.",
    )
    local_storage: dict[str, str] = Field(default_factory=dict)


def site_of(url: str | None) -> str | None:
    """The site a page is on, or `None` for a page that is not on the web."""
    if not url:
        return None
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    host = parts.hostname.lower()
    return host.removeprefix("www.")


def origin_of(url: str) -> str:
    """The scheme, host and port of `url` - what `localStorage` is keyed on."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def belongs_to(cookie_domain: str, site: str) -> bool:
    """Whether a cookie set for `cookie_domain` is part of a sign-in to `site`."""
    domain = cookie_domain.lower().lstrip(".")
    return domain == site or site.endswith(f".{domain}") or domain.endswith(f".{site}")


def cookies_for(cookies: list[dict[str, JsonValue]], site: str) -> list[dict[str, JsonValue]]:
    """The cookies of a whole browser context that belong to a sign-in to `site`."""
    kept = [
        cookie
        for cookie in cookies
        if isinstance(cookie.get("domain"), str) and belongs_to(str(cookie["domain"]), site)
    ]
    return kept[:MAX_COOKIES]


_COOKIE_PARAM_FIELDS = frozenset(
    {
        "name",
        "value",
        "domain",
        "path",
        "secure",
        "httpOnly",
        "sameSite",
        "expires",
        "priority",
        "sourceScheme",
        "sourcePort",
        "partitionKey",
    }
)
"""What `Storage.setCookies` takes of a cookie `Storage.getCookies` gave."""


def cookie_params(cookies: list[dict[str, JsonValue]]) -> list[dict[str, JsonValue]]:
    """Saved cookies as `Storage.setCookies` takes them back.

    A cookie as read carries fields that describe it rather than set it - its
    size, whether it is a session cookie - and a session cookie's `expires` of
    -1, which written back would set a cookie that expired in 1970. So only the
    settable fields go back, and a session cookie goes back without an expiry,
    which is what keeps it a session cookie.
    """
    params: list[dict[str, JsonValue]] = []
    for cookie in cookies:
        param = {key: value for key, value in cookie.items() if key in _COOKIE_PARAM_FIELDS}
        if cookie.get("session") is True:
            param.pop("expires", None)
        params.append(param)
    return params


def storage_from(raw: object) -> dict[str, str]:
    """`localStorage` as the page answered it - `[[key, value], ...]` in JSON - or nothing."""
    if not isinstance(raw, str):
        return {}
    try:
        pairs = json.loads(raw)
    except ValueError:
        return {}
    if not isinstance(pairs, list):
        return {}
    return {
        pair[0]: pair[1]
        for pair in pairs
        if isinstance(pair, list)
        and len(pair) == 2
        and isinstance(pair[0], str)
        and isinstance(pair[1], str)
    }


def bounded_storage(items: dict[str, str]) -> dict[str, str]:
    """`localStorage` as kept: a bounded number of entries, none of them huge."""
    kept = {key: value for key, value in items.items() if len(value) <= MAX_STORAGE_VALUE}
    return dict(list(kept.items())[:MAX_STORAGE_ITEMS])


def restore_script(sign_ins: list[SignIn]) -> str:
    """JavaScript that puts each sign-in's `localStorage` back on its own origin.

    Run before every document's own scripts, so a page reads its storage already
    there - and it fills only what is missing, so a value the page wrote during
    this browse is never replaced by the saved one.
    """
    stored = {
        sign_in.origin: sign_in.local_storage for sign_in in sign_ins if sign_in.local_storage
    }
    return (
        "(() => {"
        f"const saved = {json.dumps(stored)}[location.origin];"
        "if (!saved) return;"
        "try { for (const [k, v] of Object.entries(saved)) {"
        "if (localStorage.getItem(k) === null) localStorage.setItem(k, v); } } catch (e) {}"
        "})();"
    )
