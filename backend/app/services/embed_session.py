"""One visitor's conversation with an embedded agent, and the widget itself.

The session is deliberately thin. Everything that decides *what the agent may
do* - the spec, the budget, the approval gate, the tenant - is already decided
by `AgentRunnerService`; this only carries frames in and out and keeps a
transcript so a run is findable afterwards.

Three things it owns, because nothing else can:

*Identity.* A visitor is anonymous by construction. The run is attributed to the
member who published the widget (their role is what resolves what the agent may
reach) and the conversation carries no user, which is the honest record: nobody
signed in.

*Rate.* A public URL with a model behind it is somebody else's budget. The limit
is per visitor per minute, in this process - good enough for the failure it
exists to stop, which is one page hammering one socket.

*Context.* The embed's own note ("you are on the pricing page") is prepended to
the visitor's first message rather than injected into the agent's instructions:
the instructions belong to the published version, and a widget must not be able
to rewrite what an agent is.
"""

from __future__ import annotations

import logging
import time
from typing import Any
from uuid import UUID

from fastapi import WebSocket
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.budget import BudgetExceeded
from app.core.exceptions import AppException
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent_embed import AgentEmbed
from app.db.models.agent_run import RunSurface
from app.repositories import conversation_repo, member_repo
from app.services.agent_runner import AgentRunnerService

logger = logging.getLogger(__name__)

# Rolling window per (widget, visitor). In-process on purpose: this stops one
# page from hammering one socket, which is what a widget is actually exposed to.
# A distributed limit belongs in front of the deployment, not here.
_buckets: dict[tuple[str, str], tuple[int, float]] = {}
_WINDOW_SECONDS = 60.0

# What one visitor may say in a single message. Longer than any real question
# and short enough that a paste-bomb is not a model bill.
MAX_MESSAGE_CHARS = 4000


def _allowed(key: tuple[str, str], limit: int) -> bool:
    count, started = _buckets.get(key, (0, 0.0))
    now = time.monotonic()
    if now - started > _WINDOW_SECONDS:
        _buckets[key] = (1, now)
        return True
    if count >= limit:
        return False
    _buckets[key] = (count + 1, started)
    return True


class EmbedSession:
    """A single WebSocket conversation opened through a widget."""

    def __init__(
        self,
        *,
        db: AsyncSession,
        embed: AgentEmbed,
        visitor: str | None,
        websocket: WebSocket,
    ) -> None:
        self.db = db
        self.embed = embed
        # Anonymous visitors share a bucket per widget, which is the right
        # granularity: without a token there is nothing to tell them apart by,
        # and pretending otherwise (per socket) would make the limit free to
        # bypass by reconnecting.
        self.visitor = visitor or "anonymous"
        self.websocket = websocket
        self.runner = AgentRunnerService(db)
        self.conversation_id: UUID | None = None
        self._context_sent = False

    async def greet(self) -> None:
        """Tell the widget it is connected. The greeting itself is client-side."""
        await self._send({"type": "ready", "visitor": self.visitor != "anonymous"})

    async def handle(self, frame: dict[str, Any]) -> None:
        """Process one inbound frame.

        Unknown frame types are ignored rather than refused: a widget cached in
        somebody's browser may be older than this server, and closing the socket
        on it would take the conversation with it.
        """
        if frame.get("type") != "message":
            return

        text = str(frame.get("text") or "").strip()
        if not text:
            return
        if len(text) > MAX_MESSAGE_CHARS:
            await self._send(
                {"type": "error", "message": "That message is too long. Try a shorter one."}
            )
            return

        if not _allowed((str(self.embed.id), self.visitor), self.embed.rate_limit_per_minute):
            await self._send({"type": "error", "message": "You are sending messages too quickly."})
            return

        await self._send({"type": "typing"})
        try:
            answer = await self._answer(text)
        except BudgetExceeded:
            # The one failure worth naming: an operator seeing this in a widget
            # needs to know the agent hit its ceiling rather than broke.
            await self._send(
                {"type": "error", "message": "This assistant has reached its usage limit."}
            )
            return
        except AppException:
            logger.exception("embed_run_refused", extra={"embed_id": str(self.embed.id)})
            await self._send({"type": "error", "message": "This assistant is unavailable."})
            return

        await self._send({"type": "message", "role": "assistant", "text": answer})

    async def fail(self, message: str) -> None:
        await self._send({"type": "error", "message": message})

    async def close(self) -> None:
        """Nothing to release: the session owns no task and no client."""
        return

    async def _answer(self, text: str) -> str:
        ctx = await self._context()
        if self.conversation_id is None:
            conversation = await conversation_repo.create_conversation(
                self.db,
                organization_id=self.embed.organization_id,
                user_id=None,
                title=f"{self.embed.name} - {self.visitor}",
            )
            self.conversation_id = conversation.id

        prompt = text
        if self.embed.context and not self._context_sent:
            # Once per conversation, ahead of the first question. Repeating it
            # every turn would spend the same tokens to say the same thing.
            prompt = f"[Context for this placement: {self.embed.context}]\n\n{text}"
            self._context_sent = True

        answer, _run = await self.runner.execute(
            ctx,
            self.embed.agent_id,
            prompt,
            surface=RunSurface.EMBED,
            conversation_id=self.conversation_id,
        )
        return answer or "…"

    async def _context(self) -> AuthContext:
        """The role this run carries.

        The widget's owner, because an anonymous visitor has no role and an
        agent needs one to resolve what it may reach. Falling back to `viewer`
        when the owner has left the organization: their departure must not
        silently widen what a public widget can do.
        """
        role = OrgRoleName.VIEWER.value
        if self.embed.owner_user_id is not None:
            membership = await member_repo.get(
                self.db,
                organization_id=self.embed.organization_id,
                user_id=self.embed.owner_user_id,
            )
            if membership is not None:
                role = membership.role
        return AuthContext(
            user_id=self.embed.owner_user_id,
            organization_id=self.embed.organization_id,
            role=role,
        )

    async def _send(self, payload: dict[str, Any]) -> None:
        try:
            await self.websocket.send_json(payload)
        except Exception:
            # The visitor closed the tab. Nothing to recover and nobody to tell.
            logger.debug("embed_send_failed", extra={"embed_id": str(self.embed.id)})


# The widget. Plain ES5-ish JavaScript with no build step and no dependency,
# because it runs on somebody else's page: a framework here would be a version
# conflict with whatever they already load, and a bundler would be a second
# deployment artefact to keep in step with this server.
#
# `__PUBLIC_KEY__` and `__BASE_URL__` are substituted when it is served.
WIDGET_JS = """(function () {
  var KEY = "__PUBLIC_KEY__";
  var BASE = "__BASE_URL__";
  var socket = null;
  var config = null;
  var open = false;

  function el(tag, style, text) {
    var node = document.createElement(tag);
    if (style) node.setAttribute("style", style);
    if (text) node.textContent = text;
    return node;
  }

  function mount() {
    var side = config.position === "left" ? "left:24px" : "right:24px";
    var root = el("div", "position:fixed;bottom:24px;" + side + ";z-index:2147483000;" +
      "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif");

    var panel = el("div", "display:none;flex-direction:column;width:380px;max-width:calc(100vw - 48px);" +
      "height:560px;max-height:calc(100vh - 120px);background:#fff;border-radius:16px;" +
      "box-shadow:0 24px 48px rgba(0,0,0,.18);overflow:hidden;margin-bottom:12px");

    var header = el("div", "padding:16px 18px;background:" + config.accent + ";color:#fff");
    header.appendChild(el("div", "font-size:15px;font-weight:600", config.title));
    if (config.subtitle) header.appendChild(el("div", "font-size:12px;opacity:.85;margin-top:2px", config.subtitle));
    panel.appendChild(header);

    var log = el("div", "flex:1;overflow-y:auto;padding:16px;background:#f8fafc");
    panel.appendChild(log);

    var form = el("form", "display:flex;gap:8px;padding:12px;border-top:1px solid #e2e8f0;background:#fff");
    var input = el("input", "flex:1;border:1px solid #cbd5e1;border-radius:10px;padding:10px 12px;font-size:14px;outline:none");
    input.setAttribute("placeholder", config.placeholder);
    var send = el("button", "border:0;border-radius:10px;padding:10px 16px;font-size:14px;font-weight:600;" +
      "color:#fff;cursor:pointer;background:" + config.accent, "Send");
    send.setAttribute("type", "submit");
    form.appendChild(input);
    form.appendChild(send);
    panel.appendChild(form);

    var launcher = el("button", "border:0;border-radius:999px;padding:14px 20px;font-size:14px;font-weight:600;" +
      "color:#fff;cursor:pointer;box-shadow:0 8px 24px rgba(0,0,0,.18);background:" + config.accent,
      config.launcher_label);

    root.appendChild(panel);
    root.appendChild(launcher);
    document.body.appendChild(root);

    function bubble(role, text) {
      var mine = role === "user";
      var row = el("div", "display:flex;margin-bottom:10px;justify-content:" + (mine ? "flex-end" : "flex-start"));
      var body = el("div", "max-width:80%;padding:10px 12px;border-radius:14px;font-size:14px;line-height:1.5;" +
        "white-space:pre-wrap;word-break:break-word;" +
        (mine ? "background:" + config.accent + ";color:#fff" : "background:#fff;color:#0f172a;border:1px solid #e2e8f0"),
        text);
      row.appendChild(body);
      log.appendChild(row);
      log.scrollTop = log.scrollHeight;
      return body;
    }

    var pending = null;
    function connect() {
      var url = BASE.replace(/^http/, "ws") + "/api/v1/embed/" + KEY + "/ws";
      var token = window.AgenticOSToken;
      if (token) url += "?token=" + encodeURIComponent(token);
      socket = new WebSocket(url);
      socket.onmessage = function (event) {
        var frame = JSON.parse(event.data);
        if (frame.type === "typing") { pending = bubble("assistant", "…"); return; }
        if (frame.type === "message") {
          if (pending) { pending.textContent = frame.text; pending = null; }
          else bubble("assistant", frame.text);
        }
        if (frame.type === "error") {
          if (pending) { pending.remove(); pending = null; }
          bubble("assistant", frame.message);
        }
      };
      socket.onclose = function (event) {
        if (event.code === 4003) bubble("assistant", "This assistant is not available on this page.");
      };
    }

    launcher.onclick = function () {
      open = !open;
      panel.style.display = open ? "flex" : "none";
      if (open && !socket) { connect(); if (config.greeting) bubble("assistant", config.greeting); }
      if (open) input.focus();
    };

    form.onsubmit = function (event) {
      event.preventDefault();
      var text = input.value.trim();
      if (!text || !socket || socket.readyState !== 1) return;
      bubble("user", text);
      socket.send(JSON.stringify({ type: "message", text: text }));
      input.value = "";
    };
  }

  fetch(BASE + "/api/v1/embed/" + KEY + "/config")
    .then(function (r) { if (!r.ok) throw new Error("unavailable"); return r.json(); })
    .then(function (data) { config = data; if (document.body) mount(); else window.addEventListener("DOMContentLoaded", mount); })
    .catch(function () { /* A widget that cannot load stays invisible rather than broken. */ });
})();
"""
