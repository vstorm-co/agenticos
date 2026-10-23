"""Where a drawing may fetch a picture from: wherever the agent's web readers may go.

A picture's address is a request the agent chooses, and a prompt-injected one
could carry what it read in its query string. So `draw` fetches by address only
for an agent that already reads the web, and only from a host one of its readers
would itself be allowed to reach - an author's `allowed_domains` or
`blocked_domains` on `web_fetch` or `browser_use` bounds the pictures too.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from fnmatch import fnmatch

from app.agents.capabilities._registry import CapabilityBinding
from app.agents.capabilities.browser_use import WebBrowserConfig
from app.agents.capabilities.web_fetch import WebFetchConfig

WEB_REACH_RESOURCE = "web_reach"
"""Key the factory puts the agent's web reach under - see :func:`web_reach`."""


def a_label(host: str) -> str | None:
    """A hostname as `web_fetch` stores one: lower case, no trailing dot, IDNA-encoded.

    `None` for a name that has no such form, which nothing may be fetched from.
    """
    try:
        return host.strip().lower().rstrip(".").encode("idna").decode("ascii")
    except UnicodeError:
        return None


@dataclass(frozen=True)
class WebReach:
    """Where one of the agent's web readers may go."""

    allowed: tuple[str, ...] | None
    """The hosts it may reach; `None` for anywhere. An empty tuple is nowhere."""

    blocked: tuple[str, ...] = ()

    patterns: bool = False
    """Whether `allowed` holds `fnmatch` patterns (`*.example.com`), as `browser_use`
    matches them, rather than exact hosts, as `web_fetch` does."""

    def admits(self, host: str) -> bool:
        """Whether this reader would fetch from `host`."""
        if self.patterns:
            name = host.lower()
            return self.allowed is None or any(fnmatch(name, pattern) for pattern in self.allowed)
        name = a_label(host)
        if name is None or name in self.blocked:
            return False
        return self.allowed is None or name in self.allowed


def web_reach(bindings: Iterable[CapabilityBinding]) -> tuple[WebReach, ...]:
    """The reach of each web reader the agent has switched on; empty when it has none."""
    reach: list[WebReach] = []
    for binding in bindings:
        if not binding.enabled:
            continue
        if binding.capability_id == "web_fetch":
            config = WebFetchConfig.model_validate(binding.config)
            reach.append(
                WebReach(
                    allowed=_hosts(config.allowed_domains),
                    blocked=_hosts(config.blocked_domains) or (),
                )
            )
        elif binding.capability_id == "browser_use":
            allowed = WebBrowserConfig.model_validate(binding.config).allowed_domains
            reach.append(
                WebReach(
                    allowed=None if allowed is None else tuple(p.lower() for p in allowed),
                    patterns=True,
                )
            )
    return tuple(reach)


def _hosts(names: list[str] | None) -> tuple[str, ...] | None:
    if names is None:
        return None
    return tuple(host for host in map(a_label, names) if host is not None)
