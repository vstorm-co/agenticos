/**
 * Synthetic UI fixtures for the real Next application.
 * These handlers never connect to an API server or a model provider.
 */
export const THREAD = "fixture-thread";
export const AGENT = "fixture-agent";
export const USER = "fixture-user";
export const ORG = "fixture-org";
export const STAMP = "2026-11-07T08:30:00Z";
export const QUESTION = "Help me prepare a clear handover for the service desk.";
export const ANSWER = "Here is a handover the next shift can use.";
export const LONG_FILENAME =
  "service-desk-handover_november-2026_customer-success_and_operations_review_final-v12.csv";
export const LONG_AGENT =
  "Operations assistant for service desk handovers and customer follow-up";

const codeFence = String.fromCharCode(96).repeat(3);
const longUrl =
  "https://docs.example.test/operations/service-desk/handover/november-2026/customer-follow-up?reference=service_desk_handover_2026_11_07_and_pending_actions";
const assistantText = [
  ANSWER,
  "",
  "## What needs attention",
  "",
  "Three items need an owner before the next shift. The queue is stable; the open work is about follow-up and clear responsibilities.",
  "",
  "| Item | Owner | Next action | Due |",
  "| --- | --- | --- | --- |",
  "| Account access | Morgan | Confirm the invitation arrived | Today, 10:00 |",
  "| Invoice question | Alex | Send the corrected reference | Today, 11:30 |",
  "| Onboarding checklist | Sam | Review the remaining setup steps | Tomorrow |",
  "",
  "### Suggested handover",
  "",
  "Start with the open items, name the person taking each one, and include the next checkpoint. Keep customer details in the shared record.",
  "",
  "The working reference is " + longUrl + ".",
  "",
  codeFence + "javascript",
  'const handover = { team: "service-desk", reference: "customer_success_and_operations_handover_november_2026_review_and_follow_up", owner: "Morgan", status: "ready-for-review" };',
  'console.log(handover.owner, handover.status);',
  codeFence,
  "",
  "The attached export has the full list. Confirm the owners before sharing the final handover.",
].join("\n");

const user = {
  id: USER, email: "morgan@example.test", full_name: "Morgan Tan",
  is_active: true, is_app_admin: false, created_at: STAMP,
  avatar_url: null, avatar_color: 4, onboarding_completed_at: STAMP,
  locale: "en", time_zone: "UTC", impersonation: null,
  notify_budget_alerts: false, notify_approval_requests: false,
  notify_usage_reports: false, proactive_opt_out: true,
};
const organization = {
  id: ORG, name: "Studio workspace", slug: "studio-workspace",
  avatar_url: null, avatar_color: 4, is_personal: false, is_default: true,
  owner_id: USER, stripe_customer_id: null, subscription_tier: "free",
  seats_limit: null, monthly_budget_usd: null, chat_may_waive_approvals: false,
  public_live_data: false, speech_to_text_provider: null,
  speech_to_text_model: null, speech_to_text_secret_id: null,
  speech_to_text_language: null, dictation_max_seconds: 300,
  created_at: STAMP, updated_at: null,
};
const profile = {
  id: "fixture-model", label: "Workspace model", provider: "openai",
  model: "fixture-workspace-model", secret_id: "fixture-secret",
  base_url: null, api: "responses", region: null,
  params: {}, fallback_profile_ids: [], context_length: 128000,
  chat_capable: true, missing_key: false, created_at: STAMP,
};
const agent = {
  id: AGENT, slug: "operations-assistant", name: LONG_AGENT,
  description: "Prepare clear handovers and keep track of follow-up.",
  status: "published", visibility: "org", owner_user_id: USER,
  current_version_id: "fixture-version", has_avatar: false, avatar_color: 3,
  can_run: true, channels: [], categories: [], tags: [],
  context_window_tokens: 128000,
  published_model: {
    profile_id: profile.id, provider: profile.provider,
    model: profile.model, label: profile.label,
  },
  published_capabilities: [], local_coding_agent: null,
  local_workspace: false, personal_coding_harness: null,
  starters: ["Prepare a handover", "Review open follow-ups"],
  starter_icons: {}, starter_titles: {}, created_at: STAMP, updated_at: STAMP,
};
const alternateAgent = {
  ...agent, id: "fixture-agent-research", slug: "research-assistant",
  name: "Research assistant", description: "Organize notes and compare options.",
};
const agentDetail = {
  ...agent,
  draft_spec: {
    name: agent.name, instructions: "Synthetic fixture only.",
    model_profile_id: profile.id, model_settings: {},
    capabilities: [], collection_ids: [], skill_ids: [], context_ids: [],
    mcp_servers: [], subagents: [], external_agents: [],
    speech_to_text: null, voice: null,
  },
};
const permissions = [
  "agents:view", "agents:edit", "agents:publish", "agents:run",
  "workflows:view", "workflows:edit", "workflows:create", "workflows:run",
  "collections:view", "collections:edit", "skills:view", "skills:edit",
  "context:view", "context:edit", "artifacts:view", "artifacts:edit",
  "projects:view", "projects:use", "projects:edit", "approvals:decide",
  "connections:view", "connections:manage", "secrets:view", "secrets:edit",
  "mcp:manage", "channels:manage", "members:manage", "roles:manage",
  "org:settings", "budgets:manage", "runs:view", "audit:read",
  "tables:view", "tables:edit", "tables:create", "api_keys:create",
].map((permission) => ({ permission, scope: "all" }));
const conversation = {
  id: THREAD, user_id: USER,
  title: "Service desk handover and customer follow-up for November",
  created_at: STAMP, updated_at: STAMP, is_archived: false,
  is_favourite: true, agents: [agent], coding_agents: [],
  project_id: null, origin: null, unread: false,
  running_since: null, running_run_ids: [],
};
const conversations = [
  conversation,
  { ...conversation, id: "fixture-thread-2", title: "Weekly operations review", is_favourite: false },
  { ...conversation, id: "fixture-thread-3", title: "Customer onboarding checklist", is_favourite: false },
  { ...conversation, id: "fixture-thread-4", title: "Notes for the next team meeting", is_favourite: false },
];
function message(id, role, content, extra = {}) {
  return {
    id, conversation_id: THREAD, role, content, created_at: STAMP,
    agent_id: role === "assistant" ? AGENT : null,
    sender: role === "user"
      ? { user_id: USER, name: user.full_name, has_avatar: false, avatar_color: 4 }
      : null,
    model_name: role === "assistant" ? profile.label : null,
    run_status: role === "assistant" ? "completed" : null,
    run_started_at: role === "assistant" ? STAMP : null,
    run_duration_ms: role === "assistant" ? 2400 : null,
    tool_calls: [], files: [], user_rating: null,
    rating_count: { likes: 0, dislikes: 0 }, ...extra,
  };
}
export function initialMessages() {
  return [
    message("fixture-user-1", "user", QUESTION, {
      files: [{
        id: "fixture-file", filename: LONG_FILENAME,
        mime_type: "text/csv", file_type: "document", size_bytes: 12834,
      }],
    }),
    message("fixture-assistant-1", "assistant", assistantText),
    message("fixture-user-2", "user", "Make the next step easy to scan, and keep the tone neutral."),
    message("fixture-assistant-2", "assistant", [
      "## Ready for the next shift",
      "",
      "- **Morgan:** Confirm account access by 10:00.",
      "- **Alex:** Send the corrected invoice reference by 11:30.",
      "- **Sam:** Review the remaining setup steps tomorrow.",
      "",
      "Add a short note when each item is complete. If an owner is unavailable, assign a backup before the handover.",
    ].join("\n")),
  ];
}
const emptyList = { items: [], total: 0 };

/** A fresh state per viewport; no cross-test fixture contamination. */
export async function installFixture(context, { baseURL, version }) {
  const messages = initialMessages();
  const record = {
    kind: "frontend-browser-api-fixture",
    mockedRequests: [], unexpectedRequests: [], blockedExternal: [],
    sockets: [], outbound: [], submitted: [],
  };
  const chatSockets = new Set();
  const timers = new Set();
  let sequence = 0;
  let heldTurn = null;
  let holdReply = false;
  const later = (fn, delay) => {
    const timer = setTimeout(() => { timers.delete(timer); fn(); }, delay);
    timers.add(timer);
  };
  const emit = (socket, type, data = {}) => {
    try { socket.send(JSON.stringify({ type, data })); } catch { /* closed context */ }
  };
  const finish = (turn) => {
    if (!turn) return;
    messages.push(message(turn.assistantId, "assistant", turn.text));
    emit(turn.socket, "message_saved", {
      message_id: turn.assistantId, run_id: "fixture-run-" + sequence, run_status: "completed",
    });
    emit(turn.socket, "complete", { usage: null });
    emit(turn.socket, "session_ready");
    heldTurn = null;
  };

  await context.addInitScript(({ fixtureUser, orgId, agentId, appVersion, fixtureOrigin }) => {
    // An unready server can show chrome-error://; never seed storage there or on a frame's origin.
    if (window.location.origin !== fixtureOrigin) return;
    const persist = (name, state, version = 0) =>
      localStorage.setItem(name, JSON.stringify({ state, version }));
    persist("auth-storage", {
      user: fixtureUser, isAuthenticated: true, sessionOwnerId: fixtureUser.id,
    });
    persist("org-storage", { activeOrgId: orgId });
    persist("agent-selection", {
      selectedAgentId: agentId, defaultAgentId: agentId, selectedWorkflowId: null,
    }, 1);
    persist("agenticos.sidebar", {
      isCollapsed: false, openGroups: [], closedGroups: [],
    });
    persist("chat-collapsed-bands", { folded: [], opened: [] }, 2);
    persist("release-notes", { acknowledged: { [fixtureUser.id]: appVersion } });
    localStorage.setItem("theme", "light");
  }, { fixtureUser: user, orgId: ORG, agentId: AGENT, appVersion: version, fixtureOrigin: new URL(baseURL).origin });

  await context.routeWebSocket("**", (socket) => {
    const url = new URL(socket.url());
    const chat = url.pathname.endsWith("/ws/agent");
    // Next 16 Turbopack uses /_next/hmr; webpack uses /_next/webpack-hmr.
    // Turbopack delivers lazy module updates here, so a silent stub prevents hydration.
    if (url.pathname.startsWith("/_next/") && url.host === new URL(baseURL).host &&
        ["127.0.0.1", "localhost", "[::1]"].includes(url.hostname)) {
      record.sockets.push({ url: url.origin + url.pathname, mocked: false, development: true });
      socket.connectToServer();
      return;
    }
    record.sockets.push({ url: url.origin + url.pathname, mocked: true, chat });
    if (chat) {
      chatSockets.add(socket);
      later(() => emit(socket, "session_ready"), 80);
    }
    socket.onClose(() => chatSockets.delete(socket));
    socket.onMessage((raw) => {
      let payload;
      try { payload = JSON.parse(String(raw)); } catch { return; }
      record.outbound.push(payload);
      if (!chat) return;
      if (payload.type === "attach") {
        emit(socket, "session_ready");
        return;
      }
      if (payload.type === "stop") {
        finish(heldTurn);
        return;
      }
      if (typeof payload.message !== "string") return;
      sequence += 1;
      record.submitted.push(payload.message);
      const userId = "fixture-sent-user-" + sequence;
      const assistantId = "fixture-sent-assistant-" + sequence;
      messages.push(message(userId, "user", payload.message));
      const turn = {
        socket, assistantId,
        text: holdReply ? "I have the handover notes. " :
          "The handover now has a clear owner and a checkpoint for each open item.",
      };
      later(() => {
        emit(socket, "user_prompt", { message_id: userId, conversation_id: THREAD });
        emit(socket, "model_request_start");
        emit(socket, "text_delta", { index: 0, content: turn.text });
        if (holdReply) heldTurn = turn;
        else later(() => finish(turn), 140);
      }, 100);
    });
  });

  await context.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const origin = new URL(baseURL).origin;
    const method = request.method();
    if (url.origin === "https://docs.example.test" && url.pathname === "/favicon.ico" && method === "GET") {
      record.mockedRequests.push({ method, path: "synthetic-reference/favicon.ico" });
      await route.fulfill({ status: 404, contentType: "text/plain", body: "No synthetic site icon" });
      return;
    }
    if (url.origin !== origin) {
      record.blockedExternal.push({ method, url: url.origin + url.pathname });
      await route.abort("blockedbyclient");
      return;
    }
    if (!url.pathname.startsWith("/api/")) {
      await route.continue();
      return;
    }
    const path = url.pathname.slice(4).replace(/^\/v1(?=\/)/, "");
    let body;
    let status = 200;
    if (method === "GET") {
      if (path === "/auth/me") body = { ...user, access_token: "ui-craft-fixture-token" };
      else if (path === "/orgs") body = { items: [organization], total: 1 };
      else if (path === "/orgs/" + ORG) body = organization;
      else if (path === "/me/permissions") body = {
        organization_id: ORG, user_id: USER, role: "owner", is_app_admin: false, permissions,
      };
      else if (path === "/branding/notice") body = {
        maintenance_mode: false, maintenance_message: null, message: null, level: "info",
      };
      else if (path === "/releases/current") body = { release: null };
      else if (path === "/releases/latest") body = { latest: null };
      else if (path === "/notifications/unread-count") body = { count: 0, approximate: false };
      else if (path === "/assistant/signals") body = {
        pending_approvals: 0, has_agents: true, failed_run_id: null,
      };
      else if (path === "/assistant") body = {
        status: "disabled", agent_id: null, slug: null, name: "AI Architect",
        named_by_default: true, greeting: null, avatar_url: null,
        avatar_color: null, wears_mark: true, can_use: true, can_configure: true,
      };
      else if (path === "/agents") body = {
        items: [agent, alternateAgent], total: 2, categories: [], tags: [],
      };
      else if (path === "/agents/ceiling") body = { limit: null, held: null, at_limit: false };
      else if (path === "/agents/" + AGENT) body = agentDetail;
      else if (/^\/agents\/[^/]+\/dictation$/.test(path)) body = {
        engine: "browser", requested: false, server_available: false,
        unavailable: "no_provider", max_seconds: 300, provider: null, format: "wav",
      };
      else if (/^\/agents\/[^/]+\/mentionables$/.test(path)) body = emptyList;
      else if (/^\/agents\/[^/]+\/voice$/.test(path)) body = {
        available: false, unavailable: "no_voice", transport: null,
        provider: null, model: null, cap_seconds: 600,
      };
      else if (path === "/conversations") body = { items: conversations, total: conversations.length };
      else if (path === "/conversations/background-tasks") body = [];
      else if (path === "/conversations/" + THREAD) body = conversation;
      else if (path === "/conversations/" + THREAD + "/metadata") body = { project_id: null };
      else if (path === "/conversations/" + THREAD + "/messages") body = {
        items: messages, total: messages.length, cost: null,
      };
      else if (path === "/conversations/" + THREAD + "/controls") body = {
        model_profile_id: null, approval_mode: "follow_agent",
      };
      else if (path === "/conversations/" + THREAD + "/workspace") body = {
        scope: "conversation", backend: "stored", owner_label: "This conversation",
        items: [], total: 0, bytes_total: 0, truncated: false,
        bytes_limit: null, unreadable_reason: null,
      };
      else if (path === "/providers/catalog") body = {
        items: [{
          id: "openai", name: "OpenAI", secret_kind: "api_key",
          supports_base_url: true, keyless: false, apis: ["chat", "responses"],
          native_api: "responses", regions: [],
        }], total: 1,
      };
      else if (path === "/providers/model-profiles") body = { items: [profile], total: 1 };
      else if (path === "/providers/openai/models") body = {
        items: [{ id: profile.model, name: profile.label, context_length: 128000, chat_capable: true }],
        total: 1, source: "curated",
      };
      else if (path === "/secrets") body = {
        items: [{
          id: "fixture-secret", name: "Workspace connection", kind: "api_key",
          description: null, hint: "test", purpose: "openai", visibility: "org",
          owner_user_id: USER, created_at: STAMP,
        }], total: 1,
      };
      else if (path === "/secrets/kinds") body = emptyList;
      else if (path === "/secrets/purposes") body = {
        items: [{
          id: "openai", label: "OpenAI", category: "model_provider",
          kind: "api_key", help_url: null, description: "", icon: "",
        }], total: 1,
      };
      else if ([
        "/catalog/icons", "/workflows", "/projects", "/me/slash-commands",
        "/me/suggestions", "/me/suggestions/starters", "/kb", "/outcomes", "/me/mcp-connections", "/mcp-connections",
        "/approvals", "/runs/active", "/conversations/active",
        "/scheduled-tasks", "/notifications", "/usage/warnings",
      ].includes(path)) body = emptyList;
      else if (path === "/files/fixture-file") body = {
        id: "fixture-file", filename: LONG_FILENAME, mime_type: "text/csv",
        file_type: "document", size_bytes: 12834,
      };
    } else if (method === "POST" && path === "/diagnostics/presence") {
      body = null;
    } else if (method === "POST" && path === "/conversations/" + THREAD + "/read") {
      body = { ok: true };
    } else if (method === "POST" && path === "/auth/refresh") {
      body = { access_token: "ui-craft-fixture-token", token_type: "bearer" };
    }
    if (body === undefined) {
      status = 501;
      record.unexpectedRequests.push({ method, path, query: url.search });
      console.warn("[ui-craft] Fixture refused " + method + " " + path);
      body = { detail: "UI fixture has no handler for " + method + " " + path };
    } else {
      record.mockedRequests.push({ method, path });
    }
    await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
  });

  return {
    record,
    holdNextReply() { holdReply = true; },
    appendHeldReply(text) {
      if (!heldTurn) throw new Error("No held fixture turn");
      heldTurn.text += text;
      emit(heldTurn.socket, "text_delta", { index: 0, content: text });
    },
    finishHeldReply() { finish(heldTurn); holdReply = false; },
    hasHeldReply() { return heldTurn !== null; },
    dispose() { for (const timer of timers) clearTimeout(timer); },
  };
}
