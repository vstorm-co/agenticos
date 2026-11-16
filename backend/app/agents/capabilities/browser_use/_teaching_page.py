"""Read a bounded structural descriptor in the owning page's isolated world.

Uses the same pinned CDP protocol as _credential_page. This code never reads a
control value, textContent, innerText, accessible name, input name or page HTML.
"""

import hashlib
from typing import Literal

import anyio
from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from app.agents.capabilities.browser_use._credential_page import NativeCommand, NativeMethod
from app.core.browser_teaching import (
    CaptureObservation,
    StructuralTarget,
    TeachingModel,
    TeachingReason,
    TeachingRefused,
    TeachingRole,
    canonical_bytes,
)

_DESCRIBE = r"""
function (mode, x, y) {
  if (window !== window.top || location.protocol !== "https:") return null;
  const origin = location.origin;
  if (mode === "origin") return {origin, target: null, human_required: false};
  let el = mode === "point" ? document.elementFromPoint(x, y) : document.activeElement;
  for (let depth = 0; el && el.shadowRoot && depth < 8; depth++) {
    const inner = mode === "point" ? el.shadowRoot.elementFromPoint(x, y) : el.shadowRoot.activeElement;
    if (!inner || inner === el) break;
    el = inner;
  }
  const human = () => ({origin, target: null, human_required: true});
  if (!el || el.ownerDocument !== document || !el.isConnected) return null;
  if (el instanceof HTMLIFrameElement || el.closest('[data-sitekey]')) return human();
  const auth = input => input instanceof HTMLInputElement && (
    input.type === "password" || input.autocomplete.length > 256 ||
    input.autocomplete.split(/\s+/).includes("one-time-code")
  );
  const roles = new Set(["button", "link", "textbox", "combobox", "checkbox", "radio", "tab", "menuitem", "option", "switch"]);
  const roleOf = node => {
    const explicit = node.getAttribute("role");
    if (roles.has(explicit)) return explicit;
    if (node instanceof HTMLButtonElement) return "button";
    if (node instanceof HTMLAnchorElement) return "link";
    if (node instanceof HTMLSelectElement) return "combobox";
    if (node instanceof HTMLTextAreaElement || node.isContentEditable) return "textbox";
    if (node instanceof HTMLInputElement) {
      return ({text:"textbox", email:"textbox", tel:"textbox", number:"textbox", search:"textbox",
               url:"textbox", checkbox:"checkbox", radio:"radio", button:"button", submit:"button"})[node.type] || null;
    }
    return null;
  };
  let role = null;
  for (let depth = 0; el && depth < 16; depth++) {
    if (auth(el)) return human();
    role = roleOf(el);
    if (role || mode !== "point") break;
    el = el.parentElement;
  }
  if (!el || !role) return human();
  if (el.form) {
    if (el.form.elements.length > 500) return human();
    for (let i = 0; i < el.form.elements.length; i++) {
      if (auth(el.form.elements[i])) return human();
    }
  }
  const tags = new Set(["html", "body", "main", "section", "article", "div", "span", "form", "fieldset",
                        "label", "input", "textarea", "select", "button", "a", "ul", "ol", "li", "nav", "header", "footer"]);
  const structure = [];
  for (let node = el, depth = 0; node && depth < 16; depth++) {
    const nativeTag = node.tagName.toLowerCase();
    const tag = tags.has(nativeTag) ? nativeTag : "other";
    const parent = node.parentElement;
    let position = 1, visited = 0;
    for (let sibling = node.previousElementSibling; sibling; sibling = sibling.previousElementSibling) {
      if (++visited > 10000) return null;
      if (sibling.tagName === node.tagName && ++position > 10000) return null;
    }
    structure.push({tag, position});
    node = parent || (node.getRootNode() instanceof ShadowRoot ? node.getRootNode().host : null);
  }
  return {origin, target:{role, structure}, human_required:false};
}
"""


class _Frame(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    id: str = Field(min_length=1, max_length=1024)
    loaderId: str = Field(min_length=1, max_length=1024)


class _FrameTree(BaseModel):
    frame: _Frame


class _Tree(BaseModel):
    frameTree: _FrameTree


class _World(BaseModel):
    executionContextId: int = Field(ge=1)


class _Part(TeachingModel):
    tag: Literal[
        "html",
        "body",
        "main",
        "section",
        "article",
        "div",
        "span",
        "form",
        "fieldset",
        "label",
        "input",
        "textarea",
        "select",
        "button",
        "a",
        "ul",
        "ol",
        "li",
        "nav",
        "header",
        "footer",
        "other",
    ]
    position: int = Field(ge=1, le=10000)


class _Target(TeachingModel):
    role: TeachingRole
    structure: tuple[_Part, ...] = Field(min_length=1, max_length=16)


class _Observation(TeachingModel):
    origin: str = Field(max_length=2048)
    target: _Target | None
    human_required: bool


class _Result(BaseModel):
    value: _Observation


class _Answer(BaseModel):
    result: _Result
    exceptionDetails: object | None = None


class TeachingPage:
    def __init__(self, command: NativeCommand) -> None:
        self._command = command

    async def _rpc(self, method: NativeMethod, params: dict[str, JsonValue]) -> object:
        try:
            with anyio.fail_after(3):
                return await self._command(method, params)
        except Exception:
            # Browser errors can contain an echoed URL, input, script or value.
            raise TeachingRefused(TeachingReason.NATIVE_UNAVAILABLE) from None

    async def observe(
        self, mode: Literal["point", "focus", "origin"], *, x: float = 0, y: float = 0
    ) -> CaptureObservation:
        if not 0 <= x <= 4000 or not 0 <= y <= 4000:
            raise TeachingRefused(TeachingReason.NATIVE_UNAVAILABLE)
        try:
            with anyio.fail_after(6):
                frame = _Tree.model_validate(
                    await self._rpc("Page.getFrameTree", {})
                ).frameTree.frame
                world = _World.model_validate(
                    await self._rpc(
                        "Page.createIsolatedWorld",
                        {
                            "frameId": frame.id,
                            "worldName": "t3os.browser-teaching.v1",
                            "grantUniveralAccess": False,
                        },
                    )
                )
                answer = _Answer.model_validate(
                    await self._rpc(
                        "Runtime.callFunctionOn",
                        {
                            "executionContextId": world.executionContextId,
                            "functionDeclaration": _DESCRIBE,
                            "arguments": [{"value": mode}, {"value": x}, {"value": y}],
                            "silent": True,
                            "returnByValue": True,
                            "userGesture": False,
                        },
                    )
                )
                after = _Tree.model_validate(
                    await self._rpc("Page.getFrameTree", {})
                ).frameTree.frame
            if frame != after or answer.exceptionDetails is not None:
                raise TeachingRefused(TeachingReason.NATIVE_UNAVAILABLE)
            value = answer.result.value
            target = value.target
            if value.human_required and target is not None:
                raise TeachingRefused(TeachingReason.NATIVE_UNAVAILABLE)
            return CaptureObservation(
                origin=value.origin,
                human_required=value.human_required,
                target=None
                if target is None
                else StructuralTarget(
                    role=target.role,
                    fingerprint="sha256:"
                    + hashlib.sha256(canonical_bytes(target.model_dump(mode="json"))).hexdigest(),
                ),
            )
        except ValidationError, ValueError, TimeoutError:
            raise TeachingRefused(TeachingReason.NATIVE_UNAVAILABLE) from None
