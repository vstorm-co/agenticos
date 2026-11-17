"""Describe what a person's input landed on, structurally, without reading the page's words.

The observer runs in an isolated world of the top frame. It reads tag names,
sibling positions, a small set of role-defining attributes and, for
authentication detection only, input `type` and `autocomplete`. It never reads
`value`, text content, labels, accessible names, `name`/`id` attributes, the
URL beyond `location.origin`, cookies or storage. The structural path it
returns is hashed here and discarded; only the role and the hash are kept.
"""

import hashlib
from collections.abc import Awaitable, Callable
from typing import Literal

import anyio
from pydantic import BaseModel, ConfigDict, Field

from app.core.browser_teaching import Observation, Role, StructuralTarget

Mode = Literal["point", "focus", "origin"]
ObserveFn = Callable[[str, Mode, float, float], Awaitable[object]]

OBSERVE_SECONDS = 4

OBSERVER = r"""
function (mode, x, y) {
  if (window.top !== window || location.protocol !== "https:") return null;
  const origin = location.origin;
  if (mode === "origin") return {origin: origin, role: null, path: null, auth: false};
  let node = mode === "point" ? document.elementFromPoint(x, y) : document.activeElement;
  for (let hop = 0; node && node.shadowRoot && hop < 8; hop++) {
    const inner = mode === "point" ? node.shadowRoot.elementFromPoint(x, y) : node.shadowRoot.activeElement;
    if (!inner || inner === node) break;
    node = inner;
  }
  const authOnly = {origin: origin, role: null, path: null, auth: true};
  if (!node || !node.isConnected) return {origin: origin, role: null, path: null, auth: false};
  if (node.tagName === "IFRAME" || node.closest("[data-sitekey], .g-recaptcha, .h-captcha")) return authOnly;
  const secret = el => el instanceof HTMLInputElement && (
    el.type === "password" ||
    /(^|\s)(one-time-code|current-password|new-password)(\s|$)/.test(el.autocomplete || ""));
  const known = ["button", "link", "textbox", "combobox", "checkbox", "radio", "tab", "menuitem", "option", "switch"];
  const inputRoles = {text: "textbox", email: "textbox", search: "textbox", tel: "textbox", url: "textbox",
    number: "textbox", checkbox: "checkbox", radio: "radio", button: "button", submit: "button"};
  const roleOf = el => {
    const declared = el.getAttribute("role");
    if (known.includes(declared)) return declared;
    if (el instanceof HTMLButtonElement) return "button";
    if (el instanceof HTMLAnchorElement && el.hasAttribute("href")) return "link";
    if (el instanceof HTMLSelectElement) return "combobox";
    if (el instanceof HTMLTextAreaElement || el.isContentEditable) return "textbox";
    if (el instanceof HTMLInputElement) return inputRoles[el.type] || null;
    return null;
  };
  let role = null;
  for (let depth = 0; node && depth < 12; depth++) {
    if (secret(node)) return authOnly;
    role = roleOf(node);
    if (role || mode === "focus") break;
    node = node.parentElement;
  }
  if (!node || !role) return {origin: origin, role: null, path: null, auth: false};
  const form = node.form || node.closest("form");
  if (form) {
    const fields = form.querySelectorAll("input");
    if (fields.length > 400) return authOnly;
    for (const field of fields) if (secret(field)) return authOnly;
  }
  const path = [];
  for (let el = node, depth = 0; el && depth < 16; depth++) {
    let index = 0;
    for (let s = el.previousElementSibling, seen = 0; s && seen < 5000; s = s.previousElementSibling, seen++) {
      if (s.tagName === el.tagName) index++;
    }
    path.push([el.tagName.toLowerCase().slice(0, 32), index]);
    const root = el.getRootNode();
    el = el.parentElement || (root instanceof ShadowRoot ? root.host : null);
  }
  return {origin: origin, role: role, path: path, auth: false};
}
"""


class _Raw(BaseModel):
    """The observer's answer. Its fields are bounded; nothing in it is a page string except tag names."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    origin: str = Field(max_length=512)
    role: Role | None
    path: list[tuple[str, int]] | None = Field(default=None, max_length=16)
    auth: bool


class ObserveFailed(Exception):
    """The page could not be observed. Carries no page detail."""


async def observe(run: ObserveFn, mode: Mode, x: float = 0, y: float = 0) -> Observation:
    """Observe the page and return only origin, role and a fingerprint hash."""
    try:
        with anyio.fail_after(OBSERVE_SECONDS):
            value = await run(OBSERVER, mode, x, y)
        raw = _Raw.model_validate(value)
        target = None
        if raw.role is not None and raw.path:
            digest = hashlib.sha256(repr((raw.role, raw.path)).encode()).hexdigest()
            target = StructuralTarget(role=raw.role, fingerprint=f"sha256:{digest}")
        return Observation(origin=raw.origin, target=target, authentication=raw.auth)
    except Exception as exc:
        # A browser or validation error can echo a URL, script or value; keep only its type.
        raise ObserveFailed(type(exc).__name__) from None
