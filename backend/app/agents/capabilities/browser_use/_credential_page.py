"""One bounded CDP writer using private DOM references, never caller-supplied scripts.

Protocol reference: ChromeDevTools/devtools-protocol
dd55cb67621a728bba3d23e056f2de2ca1e7c906, Runtime.callFunctionOn,
Runtime.releaseObject and Page.createIsolatedWorld/getFrameTree. An objectId keeps
the call bound to the original world; a destroyed document is never retried.
"""

from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

import anyio
from pydantic import BaseModel, Field, JsonValue, SecretStr, ValidationError

from app.agents.capabilities.browser_use._elements import Element, Snapshot
from app.core.browser_fill import (
    BrowserFillObservation,
    BrowserFillReason,
    BrowserFillRefused,
    BrowserFillSelection,
)
from app.core.browser_origins import browser_origin
from app.core.sanitize import UrlRefusedError, resolve_pinned_url

NativeMethod = Literal[
    "Page.getFrameTree",
    "Page.createIsolatedWorld",
    "Runtime.callFunctionOn",
    "Runtime.evaluate",
    "Runtime.releaseObject",
]
NativeCommand = Callable[[NativeMethod, dict[str, JsonValue]], Awaitable[object]]
COMMAND_SECONDS = 5
FILL_SECONDS = 3

# This function is static application code. The selectors come only from the
# page's earlier native snapshot; fields and fresh handle UUIDs are JSON arguments.
# No page code can read this isolated world's closure or swap its DOM references.
_PREPARE = r"""
function (chosen, documentId) {
  const doc = document;
  const origin = location.origin;
  const win = window;
  if (win !== win.top || location.protocol !== "https:") return null;
  const urlOK = value => {
    const u = new URL(value, doc.baseURI);
    return u.protocol === "https:" && !u.username && !u.password && u.origin === origin;
  };
  const visible = el => {
    if (!el.isConnected || el.ownerDocument !== doc || el.disabled || el.readOnly ||
        el.closest("[inert]")) return false;
    const rect = el.getBoundingClientRect();
    const style = win.getComputedStyle(el);
    if (style.display === "none" || style.visibility !== "visible" ||
        Number(style.opacity) === 0 || rect.width <= 0 || rect.height <= 0 ||
        rect.bottom <= 0 || rect.top >= win.innerHeight ||
        rect.right <= 0 || rect.left >= win.innerWidth) return false;
    const x = Math.max(0, Math.min(win.innerWidth - 1, rect.left + rect.width / 2));
    const y = Math.max(0, Math.min(win.innerHeight - 1, rect.top + rect.height / 2));
    const hit = doc.elementFromPoint(x, y);
    return hit === el || el.contains(hit);
  };
  const role = el => {
    if (el instanceof HTMLTextAreaElement) return "textarea";
    if (el instanceof HTMLSelectElement && !el.multiple) return "select";
    if (!(el instanceof HTMLInputElement)) return null;
    return ({text: "text", email: "email", tel: "tel", password: "password",
             number: "text"})[el.type] || null;
  };
  const compatible = (field, el) => {
    const r = role(el);
    if (field === "password") return r === "password";
    if (field === "username") return ["text", "email", "tel"].includes(r) && el.type !== "number";
    if (field === "totp") return ["text", "password", "tel"].includes(r);
    if (field === "email") return ["text", "email"].includes(r);
    if (field === "phone") return ["text", "tel"].includes(r);
    return ["text", "textarea", "select"].includes(r) && el.type !== "number";
  };
  let entries;
  try {
    entries = chosen.map(item => {
      const matches = doc.querySelectorAll(item.path);
      if (matches.length !== 1) throw 0;
      const el = matches[0];
      const form = el.form;
      if (!form || form.ownerDocument !== doc || !urlOK(form.action) ||
          !["", "_self"].includes(form.target) || !visible(el) ||
          !compatible(item.field, el)) throw 0;
      return {el, form, field: item.field, handle: item.handle, role: role(el),
              type: el.type, action: form.action};
    });
    if (new Set(entries.map(e => e.el)).size !== entries.length ||
        entries.some(e => e.form !== entries[0].form)) return null;
  } catch (_) { return null; }
  let spent = false, filled = false, submitted = false;
  const valid = () => {
    if (document !== doc || window !== win || location.origin !== origin ||
        location.protocol !== "https:" || win !== win.top) return false;
    return entries.every(e => visible(e.el) && e.el.form === e.form &&
      e.el.type === e.type && role(e.el) === e.role && compatible(e.field, e.el) &&
      e.form.isConnected && e.form.action === e.action &&
      urlOK(e.form.action) && ["", "_self"].includes(e.form.target));
  };
  return {
    describe() {
      if (!valid()) return null;
      return {document_id: documentId, origin,
        fields: entries.map(e => ({field: e.field, handle: e.handle,
          role: e.role, form_origin: origin}))};
    },
    verify() { return !spent && valid(); },
    canSubmit() { return filled && !submitted && valid() && entries[0].form.method === "post"; },
    submit() {
      if (!this.canSubmit()) return "refused";
      submitted = true;
      try {
        HTMLFormElement.prototype.requestSubmit.call(entries[0].form);
        return "submitted";
      } catch (_) { return "unknown"; }
    },
    fill(values) {
      if (spent || !valid() || !Array.isArray(values) || values.length !== entries.length)
        return "refused";
      const normalized = [];
      for (let i = 0; i < entries.length; ++i) {
        const e = entries[i], value = values[i];
        if (typeof value !== "string" || value.length > 16384) return "refused";
        if (e.el instanceof HTMLSelectElement) {
          const options = Array.from(e.el.options).filter(o => !o.disabled &&
            (o.value === value || o.text === value));
          if (options.length !== 1) return "refused";
          normalized.push(options[0].value);
        } else {
          if (e.el.maxLength >= 0 && value.length > e.el.maxLength) return "refused";
          normalized.push(value);
        }
      }
      spent = true;
      let wrote = false;
      try {
        for (let i = 0; i < entries.length; ++i) {
          if (!valid()) return wrote ? "unknown" : "refused";
          const e = entries[i];
          const prototype = e.el instanceof HTMLSelectElement ? HTMLSelectElement.prototype :
            e.el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
          Object.getOwnPropertyDescriptor(prototype, "value").set.call(e.el, normalized[i]);
          wrote = true;
          e.el.dispatchEvent(new Event("input", {bubbles: true}));
          e.el.dispatchEvent(new Event("change", {bubbles: true}));
        }
        filled = true;
        return "filled";
      } catch (_) { return wrote ? "unknown" : "refused"; }
    }
  };
}
"""
_DESCRIBE = "function () { return this.describe(); }"
_VERIFY = "function () { return this.verify(); }"
_CAN_SUBMIT = "function () { return this.canSubmit(); }"
_SUBMIT = "function () { return this.submit(); }"
_FILL = "function (values) { return this.fill(values); }"


_PROTECTED_FORM = r"""
function(expectedOrigin) {
  if (window !== window.top || location.origin !== expectedOrigin) return [];
  const path = el => {
    const parts = [];
    while (el && el.nodeType === Node.ELEMENT_NODE) {
      const tag = el.localName;
      const siblings = el.parentElement ? Array.from(el.parentElement.children).filter(e => e.localName === tag) : [el];
      parts.unshift(tag + ":nth-of-type(" + (siblings.indexOf(el) + 1) + ")");
      el = el.parentElement;
    }
    return parts.join(" > ");
  };
  const result = [];
  for (const el of document.querySelectorAll("input, textarea, select")) {
    if (result.length >= 200) break;
    const form = el.form, rect = el.getBoundingClientRect(), style = getComputedStyle(el);
    if (!form || el.disabled || el.readOnly || el.closest("[inert]") ||
        style.display === "none" || style.visibility !== "visible" || Number(style.opacity) === 0 ||
        rect.width <= 0 || rect.height <= 0 || rect.top >= innerHeight || rect.bottom <= 0 ||
        rect.left >= innerWidth || rect.right <= 0) continue;
    const destination = new URL(form.action, document.baseURI);
    if (destination.origin !== expectedOrigin || destination.username || destination.password) continue;
    let role = el instanceof HTMLTextAreaElement ? "textarea" :
      el instanceof HTMLSelectElement && !el.multiple ? "select" :
      el instanceof HTMLInputElement ? ({text:"text",email:"email",password:"password",tel:"tel",number:"text"})[el.type] : null;
    if (!role) continue;
    const hint = role === "password" ? "password" :
      el.autocomplete === "username" ? "username" :
      el.autocomplete === "one-time-code" ? "one-time-code" : "unknown";
    result.push({index:result.length + 1, role, hint, path:path(el)});
  }
  return result;
}
"""


class _Control(BaseModel):
    index: int = Field(ge=1, le=200)
    role: Literal["text", "email", "password", "tel", "textarea", "select"]
    hint: Literal["username", "password", "one-time-code", "unknown"]
    path: str = Field(min_length=1, max_length=4096)


class _Controls(BaseModel):
    items: list[_Control] = Field(max_length=200)


class _Frame(BaseModel):
    id: str = Field(min_length=1, max_length=1024)
    loaderId: str = Field(min_length=1, max_length=1024)


class _Tree(BaseModel):
    frame: _Frame


class _FrameAnswer(BaseModel):
    frameTree: _Tree


class _World(BaseModel):
    executionContextId: int = Field(gt=0, strict=True)


class _RemoteValue(BaseModel):
    type: str
    objectId: str | None = Field(default=None, max_length=2048)
    value: JsonValue = None


class _Answer(BaseModel):
    result: _RemoteValue


@dataclass(frozen=True)
class NativeFillValues:
    """Values exist only between the committed claim and the one native call."""

    items: tuple[SecretStr, ...]


async def public_destination(origin: str) -> None:
    """Reject private answers even when an agent's normal browser allowlist permits them."""
    try:
        normalized = browser_origin(origin)
        with anyio.fail_after(COMMAND_SECONDS):
            await anyio.to_thread.run_sync(
                lambda: resolve_pinned_url(normalized, allowed_schemes=frozenset({"https"})),
                abandon_on_cancel=True,
            )
    except UrlRefusedError, ValueError, OSError, TimeoutError:
        raise BrowserFillRefused(BrowserFillReason.DESTINATION_REFUSED) from None


class CredentialPage:
    """Internal adapter owned by a CdpPage. It never connects to a caller's endpoint."""

    def __init__(self, send: NativeCommand) -> None:
        self._send = send
        self._object: str | None = None
        self._frame: _Frame | None = None
        self.observation: BrowserFillObservation | None = None
        self._spent = False
        self._filled = False
        self._submitted = False

    async def _rpc(self, method: NativeMethod, params: dict[str, JsonValue]) -> object:
        try:
            with anyio.fail_after(COMMAND_SECONDS):
                result = await self._send(method, params)
        except Exception:
            # CDP clients have transport-specific errors that may quote arguments.
            # Cancellation remains a BaseException and is handled by the owning writer.
            raise BrowserFillRefused(BrowserFillReason.PROVIDER_UNAVAILABLE) from None
        if not isinstance(result, dict) or "exceptionDetails" in result:
            raise BrowserFillRefused(BrowserFillReason.DOCUMENT_CHANGED)
        return result

    async def _tree(self) -> _Frame:
        try:
            answer = _FrameAnswer.model_validate(await self._rpc("Page.getFrameTree", {}))
        except ValidationError:
            raise BrowserFillRefused(BrowserFillReason.DOCUMENT_CHANGED) from None
        return answer.frameTree.frame

    async def origin(self) -> str:
        try:
            answer = _Answer.model_validate(
                await self._rpc(
                    "Runtime.evaluate",
                    {
                        "expression": "location.origin",
                        "returnByValue": True,
                        "silent": True,
                        "includeCommandLineAPI": False,
                        "timeout": 1000,
                    },
                )
            )
            if not isinstance(answer.result.value, str):
                return ""
            return browser_origin(answer.result.value)
        except ValueError:
            return ""

    async def _call(self, declaration: str, args: list[JsonValue] | None = None) -> JsonValue:
        if self._object is None:
            raise BrowserFillRefused(BrowserFillReason.DOCUMENT_CHANGED)
        try:
            answer = _Answer.model_validate(
                await self._rpc(
                    "Runtime.callFunctionOn",
                    {
                        "objectId": self._object,
                        "functionDeclaration": declaration,
                        "arguments": [{"value": value} for value in (args or [])],
                        "silent": True,
                        "returnByValue": True,
                        "userGesture": False,
                    },
                )
            )
        except ValidationError:
            raise BrowserFillRefused(BrowserFillReason.DOCUMENT_CHANGED) from None
        return answer.result.value

    async def protected_snapshot(self, origin: str) -> Snapshot:
        """Only fixed control roles and internal paths; no labels, values, URLs or page text."""
        frame = await self._tree()
        try:
            world = _World.model_validate(
                await self._rpc(
                    "Page.createIsolatedWorld",
                    {"frameId": frame.id, "worldName": str(uuid4()), "grantUniveralAccess": False},
                )
            )
            answer = _Answer.model_validate(
                await self._rpc(
                    "Runtime.callFunctionOn",
                    {
                        "executionContextId": world.executionContextId,
                        "functionDeclaration": _PROTECTED_FORM,
                        "arguments": [{"value": origin}],
                        "silent": True,
                        "returnByValue": True,
                        "userGesture": False,
                    },
                )
            )
            controls = _Controls.model_validate({"items": answer.result.value})
        except ValidationError:
            raise BrowserFillRefused(BrowserFillReason.DOCUMENT_CHANGED) from None
        if await self._tree() != frame:
            raise BrowserFillRefused(BrowserFillReason.DOCUMENT_CHANGED)
        labels = {
            "username": "Username field",
            "password": "Password field",
            "one-time-code": "Verification code field",
            "unknown": "Protected form field",
        }
        roles = {"text": "textbox", "textarea": "textbox", "select": "combobox"}
        return Snapshot(
            url=origin,
            title="Protected browser session",
            elements=tuple(
                Element(
                    index=item.index,
                    role=roles.get(item.role, item.role),
                    label=labels[item.hint],
                    path=item.path,
                )
                for item in controls.items
            ),
            text="Page text and images remain hidden. Only fixed form-control roles are shown.",
        )

    async def prepare(
        self, selection: BrowserFillSelection, snapshot: Snapshot
    ) -> BrowserFillObservation:
        await self.close()
        elements = {item.index: item for item in snapshot.elements}
        chosen: list[JsonValue] = []
        for item in selection.fields:
            element = elements.get(item.element_id)
            if element is None or not element.path or len(element.path) > 4096:
                raise BrowserFillRefused(BrowserFillReason.FIELD_REFUSED)
            chosen.append({"field": item.field, "path": element.path, "handle": str(uuid4())})
        frame = await self._tree()
        try:
            world = _World.model_validate(
                await self._rpc(
                    "Page.createIsolatedWorld",
                    {"frameId": frame.id, "worldName": str(uuid4()), "grantUniveralAccess": False},
                )
            )
            answer = _Answer.model_validate(
                await self._rpc(
                    "Runtime.callFunctionOn",
                    {
                        "executionContextId": world.executionContextId,
                        "functionDeclaration": _PREPARE,
                        "arguments": [{"value": chosen}, {"value": str(uuid4())}],
                        "silent": True,
                        "returnByValue": False,
                        "userGesture": False,
                    },
                )
            )
        except ValidationError:
            raise BrowserFillRefused(BrowserFillReason.FIELD_REFUSED) from None
        if answer.result.objectId is None:
            raise BrowserFillRefused(BrowserFillReason.FIELD_REFUSED)
        self._object = answer.result.objectId
        self._frame = frame
        self._spent = False
        self._filled = False
        self._submitted = False
        try:
            observed = BrowserFillObservation.model_validate(await self._call(_DESCRIBE))
        except ValidationError:
            await self.close()
            raise BrowserFillRefused(BrowserFillReason.FIELD_REFUSED) from None
        self.observation = observed
        await self.verify()
        return observed

    async def verify(self) -> BrowserFillObservation:
        if self.observation is None or self._spent or await self._tree() != self._frame:
            raise BrowserFillRefused(BrowserFillReason.DOCUMENT_CHANGED)
        await public_destination(self.observation.origin)
        if await self._call(_VERIFY) is not True:
            raise BrowserFillRefused(BrowserFillReason.DOCUMENT_CHANGED)
        return self.observation

    async def fill(self, values: Callable[[], NativeFillValues]) -> bool:
        """One attempt. A lost response, cancellation or partial effect is never retried."""
        if self._spent or self.observation is None:
            raise BrowserFillRefused(BrowserFillReason.ALREADY_CONSUMED)
        await self.verify()
        prepared = values()
        if len(prepared.items) != len(self.observation.fields):
            raise BrowserFillRefused(BrowserFillReason.FIELD_REFUSED)
        self._spent = True
        try:
            with anyio.fail_after(FILL_SECONDS):
                result = await self._call(
                    _FILL, [[value.get_secret_value() for value in prepared.items]]
                )
        except BrowserFillRefused, TimeoutError:
            return False
        self._filled = result == "filled"
        return self._filled

    async def verify_submission(self) -> BrowserFillObservation:
        if (
            not self._filled
            or self._submitted
            or self.observation is None
            or await self._tree() != self._frame
        ):
            raise BrowserFillRefused(BrowserFillReason.DOCUMENT_CHANGED)
        await public_destination(self.observation.origin)
        if await self._call(_CAN_SUBMIT) is not True:
            raise BrowserFillRefused(BrowserFillReason.DOCUMENT_CHANGED)
        return self.observation

    async def submit(self) -> bool:
        """Only after a separate durable owner decision; an uncertain submit is terminal."""
        await self.verify_submission()
        self._submitted = True
        try:
            with anyio.fail_after(FILL_SECONDS):
                result = await self._call(_SUBMIT)
        except BrowserFillRefused, TimeoutError:
            return False
        return result == "submitted"

    async def close(self) -> None:
        object_id, self._object = self._object, None
        self.observation, self._frame = None, None
        self._spent = True
        self._filled = False
        self._submitted = True
        if object_id is not None:
            with anyio.move_on_after(COMMAND_SECONDS, shield=True):
                with suppress(BrowserFillRefused):
                    await self._rpc("Runtime.releaseObject", {"objectId": object_id})
