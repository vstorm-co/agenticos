/**
 * @vitest-environment node
 *
 * These are server routes. The suite's default environment is jsdom, where
 * `request.formData()` never resolves - the multipart parser wants a real
 * stream - and running route handlers in a browser-shaped global is a lie about
 * where they execute anyway.
 */
import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { GET as health } from "./health/route";
import { POST as acceptInvitation, DELETE as declineInvitation } from "./invitations/[token]/route";
import {
  GET as readChannelLink,
  POST as confirmChannelLink,
  DELETE as unlinkChannelAccount,
} from "./me/channel-link/[token]/route";
import { GET as listChannelAccounts } from "./me/channel-link/route";
import { GET as listConnections, POST as createConnection } from "./me/mcp-connections/route";
import {
  PATCH as patchConnection,
  DELETE as deleteConnection,
} from "./me/mcp-connections/[id]/route";
import { POST as testConnection } from "./me/mcp-connections/[id]/test/route";
import { POST as startOauth } from "./me/mcp-connections/oauth/start/route";
import { PUT as upsertBuiltin } from "./me/slash-commands/builtin/route";
import { POST as createCommand } from "./me/slash-commands/custom/route";
import { GET as listCommands } from "./me/slash-commands/route";
import { PATCH as patchCommand, DELETE as deleteCommand } from "./me/slash-commands/[id]/route";
import { GET as listIntegrations, POST as createIntegration } from "./orgs/[id]/integrations/route";
import { GET as connectors } from "./orgs/[id]/integrations/connectors/route";
import { DELETE as deleteIntegration } from "./orgs/[id]/integrations/[sourceId]/route";
import { POST as triggerIntegration } from "./orgs/[id]/integrations/[sourceId]/trigger/route";
import { GET as listInvitations, POST as createInvitation } from "./orgs/[id]/invitations/route";
import { DELETE as revokeInvitation } from "./orgs/[id]/invitations/[invitationId]/route";
import { GET as members } from "./orgs/[id]/members/route";
import { PATCH as patchMember, DELETE as removeMember } from "./orgs/[id]/members/[userId]/route";
import { GET as getOrg, PATCH as patchOrg, DELETE as deleteOrg } from "./orgs/[id]/route";
import { GET as listOrgs, POST as createOrg } from "./orgs/route";
import { DELETE as revokeSession } from "./sessions/[id]/route";
import { GET as listSessions, DELETE as revokeOtherSessions } from "./sessions/route";
import { GET as getMe, PATCH as patchMe } from "./users/me/route";
import { BackendApiError, backendFetch } from "@/lib/server-api";

vi.mock("@/lib/server-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/server-api")>("@/lib/server-api");
  return { ...actual, backendFetch: vi.fn() };
});

/** A signed-in request, unless `signedIn` says otherwise. */
function request(
  url = "http://localhost:3000/api/orgs",
  { body, signedIn = true }: { body?: unknown; signedIn?: boolean } = {},
): NextRequest {
  return new NextRequest(url, {
    headers: signedIn ? { cookie: "access_token=at" } : {},
    ...(body === undefined ? {} : { method: "POST", body: JSON.stringify(body) }),
  });
}

const org = { params: Promise.resolve({ id: "org-1" }) };

/**
 * Every route that reads the session cookie itself, with a call that should
 * reach the backend.
 *
 * Two invariants, and both are the kind that fail silently. A route that forgot
 * to check the cookie forwards an unauthenticated request and lets the backend
 * decide, which turns a 401 into whatever that endpoint does with no token. And
 * a route that forgot to forward the token asks the backend as nobody, which for
 * a listing endpoint answers an empty list rather than an error - a page that
 * says "nothing here" about data that plainly exists.
 */
const COOKIE_GATED: [string, (signedIn: boolean) => Promise<Response>][] = [
  [
    "the chat account a link URL is about",
    (s) =>
      readChannelLink(request("http://localhost:3000/api/me/channel-link/tok", { signedIn: s }), {
        params: Promise.resolve({ token: "tok" }),
      }),
  ],
  [
    "the chat accounts somebody has connected",
    (s) =>
      listChannelAccounts(request("http://localhost:3000/api/me/channel-link", { signedIn: s })),
  ],
  [
    "disconnecting a chat account",
    (s) =>
      unlinkChannelAccount(
        request("http://localhost:3000/api/me/channel-link/i-1", { signedIn: s }),
        { params: Promise.resolve({ token: "i-1" }) },
      ),
  ],
  [
    "confirming a chat account is yours",
    (s) =>
      confirmChannelLink(
        request("http://localhost:3000/api/me/channel-link/tok", { signedIn: s }),
        { params: Promise.resolve({ token: "tok" }) },
      ),
  ],
  [
    "the organization list",
    (s) => listOrgs(request("http://localhost:3000/api/orgs", { signedIn: s })),
  ],
  [
    "creating an organization",
    (s) =>
      createOrg(request("http://localhost:3000/api/orgs", { body: { name: "Acme" }, signedIn: s })),
  ],
  [
    "one organization",
    (s) => getOrg(request("http://localhost:3000/api/orgs/org-1", { signedIn: s }), org),
  ],
  [
    "renaming an organization",
    (s) =>
      patchOrg(
        request("http://localhost:3000/api/orgs/org-1", { body: { name: "Beta" }, signedIn: s }),
        org,
      ),
  ],
  [
    "deleting an organization",
    (s) => deleteOrg(request("http://localhost:3000/api/orgs/org-1", { signedIn: s }), org),
  ],
  [
    "the member list",
    (s) => members(request("http://localhost:3000/api/orgs/org-1/members", { signedIn: s }), org),
  ],
  [
    "a role change",
    (s) =>
      patchMember(
        request("http://localhost:3000/api/orgs/org-1/members/u-1", {
          body: { role: "admin" },
          signedIn: s,
        }),
        { params: Promise.resolve({ id: "org-1", userId: "u-1" }) },
      ),
  ],
  [
    "removing a member",
    (s) =>
      removeMember(request("http://localhost:3000/api/orgs/org-1/members/u-1", { signedIn: s }), {
        params: Promise.resolve({ id: "org-1", userId: "u-1" }),
      }),
  ],
  [
    "the invitation list",
    (s) =>
      listInvitations(
        request("http://localhost:3000/api/orgs/org-1/invitations", { signedIn: s }),
        org,
      ),
  ],
  [
    "sending an invitation",
    (s) =>
      createInvitation(
        request("http://localhost:3000/api/orgs/org-1/invitations", {
          body: { email: "a@example.com" },
          signedIn: s,
        }),
        org,
      ),
  ],
  [
    "revoking an invitation",
    (s) =>
      revokeInvitation(
        request("http://localhost:3000/api/orgs/org-1/invitations/inv-1", { signedIn: s }),
        { params: Promise.resolve({ id: "org-1", invitationId: "inv-1" }) },
      ),
  ],
  [
    "the integration list",
    (s) =>
      listIntegrations(
        request("http://localhost:3000/api/orgs/org-1/integrations", { signedIn: s }),
        org,
      ),
  ],
  [
    "creating an integration",
    (s) =>
      createIntegration(
        request("http://localhost:3000/api/orgs/org-1/integrations", {
          body: { name: "Drive" },
          signedIn: s,
        }),
        org,
      ),
  ],
  [
    "the connector list",
    (s) =>
      connectors(
        request("http://localhost:3000/api/orgs/org-1/integrations/connectors", { signedIn: s }),
        org,
      ),
  ],
  [
    "removing an integration",
    (s) =>
      deleteIntegration(
        request("http://localhost:3000/api/orgs/org-1/integrations/s-1", { signedIn: s }),
        { params: Promise.resolve({ id: "org-1", sourceId: "s-1" }) },
      ),
  ],
  [
    "triggering a sync",
    (s) =>
      triggerIntegration(
        request("http://localhost:3000/api/orgs/org-1/integrations/s-1/trigger", { signedIn: s }),
        { params: Promise.resolve({ id: "org-1", sourceId: "s-1" }) },
      ),
  ],
  [
    "accepting an invitation",
    (s) =>
      acceptInvitation(request("http://localhost:3000/api/invitations/tok", { signedIn: s }), {
        params: Promise.resolve({ token: "tok" }),
      }),
  ],
  [
    "declining an invitation",
    (s) =>
      declineInvitation(request("http://localhost:3000/api/invitations/tok", { signedIn: s }), {
        params: Promise.resolve({ token: "tok" }),
      }),
  ],
  [
    "the session list",
    (s) => listSessions(request("http://localhost:3000/api/sessions", { signedIn: s })),
  ],
  [
    "signing other sessions out",
    (s) => revokeOtherSessions(request("http://localhost:3000/api/sessions", { signedIn: s })),
  ],
  [
    "revoking one session",
    (s) =>
      revokeSession(request("http://localhost:3000/api/sessions/s-1", { signedIn: s }), {
        params: Promise.resolve({ id: "s-1" }),
      }),
  ],
  [
    "the caller's own profile",
    (s) => getMe(request("http://localhost:3000/api/users/me", { signedIn: s })),
  ],
  [
    "editing the caller's profile",
    (s) =>
      patchMe(
        request("http://localhost:3000/api/users/me", { body: { full_name: "K" }, signedIn: s }),
      ),
  ],
  [
    "the caller's connections",
    (s) =>
      listConnections(request("http://localhost:3000/api/me/mcp-connections", { signedIn: s })),
  ],
  [
    "adding a connection",
    (s) =>
      createConnection(
        request("http://localhost:3000/api/me/mcp-connections", {
          body: { name: "linear", url: "https://mcp/sse" },
          signedIn: s,
        }),
      ),
  ],
  [
    "editing a connection",
    (s) =>
      patchConnection(
        request("http://localhost:3000/api/me/mcp-connections/c-1", {
          body: { is_enabled: false },
          signedIn: s,
        }),
        { params: Promise.resolve({ id: "c-1" }) },
      ),
  ],
  [
    "removing a connection",
    (s) =>
      deleteConnection(
        request("http://localhost:3000/api/me/mcp-connections/c-1", { signedIn: s }),
        {
          params: Promise.resolve({ id: "c-1" }),
        },
      ),
  ],
  [
    "checking a connection",
    (s) =>
      testConnection(
        request("http://localhost:3000/api/me/mcp-connections/c-1/test", { signedIn: s }),
        { params: Promise.resolve({ id: "c-1" }) },
      ),
  ],
  [
    "starting an OAuth flow",
    (s) =>
      startOauth(
        request("http://localhost:3000/api/me/mcp-connections/oauth/start", {
          body: { name: "linear", url: "https://mcp/sse" },
          signedIn: s,
        }),
      ),
  ],
  [
    "the caller's slash commands",
    (s) => listCommands(request("http://localhost:3000/api/me/slash-commands", { signedIn: s })),
  ],
  [
    "switching a built-in",
    (s) =>
      upsertBuiltin(
        request("http://localhost:3000/api/me/slash-commands/builtin", {
          body: { name: "summarise", is_enabled: false },
          signedIn: s,
        }),
      ),
  ],
  [
    "creating a command",
    (s) =>
      createCommand(
        request("http://localhost:3000/api/me/slash-commands/custom", {
          body: { name: "standup", prompt: "x" },
          signedIn: s,
        }),
      ),
  ],
  [
    "editing a command",
    (s) =>
      patchCommand(
        request("http://localhost:3000/api/me/slash-commands/sc-1", {
          body: { name: "daily" },
          signedIn: s,
        }),
        { params: Promise.resolve({ id: "sc-1" }) },
      ),
  ],
  [
    "removing a command",
    (s) =>
      deleteCommand(request("http://localhost:3000/api/me/slash-commands/sc-1", { signedIn: s }), {
        params: Promise.resolve({ id: "sc-1" }),
      }),
  ],
];

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(backendFetch).mockResolvedValue({ items: [], total: 0 });
});

describe("the routes that read the session cookie", () => {
  it.each(COOKIE_GATED)("refuses %s without a session", async (_name, call) => {
    const response = await call(false);

    expect(response.status).toBe(401);
    expect(backendFetch).not.toHaveBeenCalled();
  });

  it.each(COOKIE_GATED)("forwards %s with the caller's own token", async (_name, call) => {
    // Not forwarding it is the quiet failure: the backend answers as nobody,
    // which for a listing is an empty list rather than an error.
    await call(true);

    expect(backendFetch).toHaveBeenCalledTimes(1);
    expect(vi.mocked(backendFetch).mock.calls[0]![1]).toMatchObject({
      headers: expect.objectContaining({ Authorization: "Bearer at" }),
    });
  });

  it.each(COOKIE_GATED)("passes the backend's refusal of %s through", async (_name, call) => {
    vi.mocked(backendFetch).mockRejectedValue(new BackendApiError(403, "Forbidden", null));

    const response = await call(true);

    expect(response.status).toBe(403);
  });

  it.each(COOKIE_GATED)("answers 500 when %s could not be forwarded", async (_name, call) => {
    vi.mocked(backendFetch).mockRejectedValue(new Error("ECONNREFUSED"));

    const response = await call(true);

    expect(response.status).toBe(500);
  });

  it.each(COOKIE_GATED)("addresses %s under the platform's v1 prefix", async (_name, call) => {
    // The one thing a copied route file gets wrong: forwarding to a path that
    // does not exist, which answers 404 and renders as an empty page.
    await call(true);

    expect(vi.mocked(backendFetch).mock.calls[0]![0]).toMatch(/^\/api\/v1\//);
  });
});

describe("the paths each one addresses", () => {
  it("names the organization, member, invitation and integration in the path", async () => {
    await patchMember(
      request("http://localhost:3000/api/orgs/org-1/members/u-1", { body: { role: "admin" } }),
      { params: Promise.resolve({ id: "org-1", userId: "u-1" }) },
    );
    expect(vi.mocked(backendFetch).mock.calls[0]![0]).toBe("/api/v1/orgs/org-1/members/u-1");

    vi.mocked(backendFetch).mockClear();
    await revokeInvitation(request("http://localhost:3000/api/orgs/org-1/invitations/inv-1"), {
      params: Promise.resolve({ id: "org-1", invitationId: "inv-1" }),
    });
    expect(vi.mocked(backendFetch).mock.calls[0]![0]).toBe("/api/v1/orgs/org-1/invitations/inv-1");
  });

  it("addresses an org integration by source, naming the organization in a header", async () => {
    // These live under `/org/integrations` on the backend rather than nested
    // under an organization id, so the tenant travels in `X-Organization-Id` -
    // and a route that dropped the header would act on the caller's personal
    // organization instead.
    await triggerIntegration(
      request("http://localhost:3000/api/orgs/org-1/integrations/s-1/trigger"),
      { params: Promise.resolve({ id: "org-1", sourceId: "s-1" }) },
    );

    expect(vi.mocked(backendFetch).mock.calls[0]![0]).toBe("/api/v1/org/integrations/s-1/trigger");
    expect(vi.mocked(backendFetch).mock.calls[0]![1]).toMatchObject({
      headers: expect.objectContaining({ "X-Organization-Id": "org-1" }),
    });
  });

  it("accepts an invitation on the accept endpoint, and declines on the invitation itself", async () => {
    // Two different backend routes, and posting to the wrong one is how an
    // accept screen once announced success to somebody who had joined nothing.
    await acceptInvitation(request("http://localhost:3000/api/invitations/tok"), {
      params: Promise.resolve({ token: "tok" }),
    });
    expect(vi.mocked(backendFetch).mock.calls[0]![0]).toBe("/api/v1/invitations/tok/accept");

    vi.mocked(backendFetch).mockClear();
    await declineInvitation(request("http://localhost:3000/api/invitations/tok"), {
      params: Promise.resolve({ token: "tok" }),
    });
    expect(vi.mocked(backendFetch).mock.calls[0]![0]).toBe("/api/v1/invitations/tok");
  });

  it("escapes a session id on its way into the path", async () => {
    await revokeSession(request("http://localhost:3000/api/sessions/a%2Fb"), {
      params: Promise.resolve({ id: "a/b" }),
    });

    expect(vi.mocked(backendFetch).mock.calls[0]![0]).toBe("/api/v1/sessions/a%2Fb");
  });

  it("carries the session list's paging", async () => {
    await listSessions(request("http://localhost:3000/api/sessions?skip=10&limit=5"));

    expect(vi.mocked(backendFetch).mock.calls[0]![0]).toContain("skip=10");
  });

  it("asks for every session when none was paged", async () => {
    await listSessions(request("http://localhost:3000/api/sessions"));

    expect(vi.mocked(backendFetch).mock.calls[0]![0]).toBe("/api/v1/sessions");
  });
});

describe("the health check", () => {
  it("answers what the backend said", async () => {
    vi.mocked(backendFetch).mockResolvedValue({ status: "ok" });

    const response = await health();

    await expect(response.json()).resolves.toEqual({ status: "ok" });
  });

  it("says the backend is unavailable, with its own status", async () => {
    // A health check needs no session: it is what a load balancer asks.
    vi.mocked(backendFetch).mockRejectedValue(new BackendApiError(503, "Unavailable", null));

    const response = await health();

    expect(response.status).toBe(503);
    await expect(response.json()).resolves.toEqual({ detail: "Backend service unavailable" });
  });

  it("answers 500 when the backend could not be reached at all", async () => {
    vi.mocked(backendFetch).mockRejectedValue(new Error("ECONNREFUSED"));

    const response = await health();

    expect(response.status).toBe(500);
  });
});
