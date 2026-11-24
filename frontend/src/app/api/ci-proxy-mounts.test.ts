import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { GET as mfaGet, POST as mfaPost } from "./auth/mfa/[...path]/route";
import { GET as patternsGet } from "./failure-learning/[[...path]]/route";
import { GET as agentMessagesGet } from "./agent-messages/[[...path]]/route";
import { GET as appConnectionsGet } from "./me/app-connections/[[...path]]/route";
import { POST as onboardingPost } from "./onboarding/[[...path]]/route";

const mounts = [
  { path: "/auth/mfa/status", method: "GET", handler: mfaGet, body: undefined },
  { path: "/auth/mfa/setup", method: "POST", handler: mfaPost, body: undefined },
  { path: "/auth/mfa/enable", method: "POST", handler: mfaPost, body: '{"code":"123456"}' },
  { path: "/auth/mfa/disable", method: "POST", handler: mfaPost, body: '{"code":"123456"}' },
  { path: "/auth/mfa/recovery-codes", method: "POST", handler: mfaPost, body: '{"code":"123456"}' },
  { path: "/failure-learning/patterns", method: "GET", handler: patternsGet, body: undefined },
  { path: "/agent-messages", method: "GET", handler: agentMessagesGet, body: undefined },
  { path: "/me/app-connections", method: "GET", handler: appConnectionsGet, body: undefined },
  { path: "/onboarding/team-proposal", method: "POST", handler: onboardingPost, body: "{}" },
] as const;

function request(mount: (typeof mounts)[number], authenticated = true) {
  const req = new NextRequest(`http://localhost:3000/api${mount.path}`, {
    method: mount.method,
    headers: {
      "Content-Type": "application/json",
      "X-Organization-Id": "org-a",
      Authorization: "Bearer ignored-client-token",
    },
    body: mount.body,
  });
  if (authenticated) req.cookies.set("agenticos_access_token", "session-token");
  return req;
}

afterEach(() => vi.unstubAllGlobals());

describe.each(mounts)("$method $path proxy mount", (mount) => {
  it("forwards the authenticated request and active organization to the existing backend route", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValue(Response.json({ result: "accepted" }));
    vi.stubGlobal("fetch", fetchMock);
    const response = await mount.handler(request(mount));

    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock).toHaveBeenCalledWith(
      `http://localhost:8000/api/v1${mount.path}`,
      expect.objectContaining({
        method: mount.method,
        headers: {
          Authorization: "Bearer session-token",
          "Content-Type": "application/json",
          "X-Organization-Id": "org-a",
        },
        cache: "no-store",
      }),
    );
    const forwarded = fetchMock.mock.calls[0]?.[1];
    expect(
      forwarded?.body instanceof ArrayBuffer
        ? new TextDecoder().decode(forwarded.body)
        : forwarded?.body,
    ).toBe(mount.method === "POST" ? (mount.body ?? "") : undefined);
    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(await response.json()).toEqual({ result: "accepted" });
  });

  it("refuses a missing session before reaching the backend", async () => {
    const fetchMock = vi.fn<typeof fetch>();
    vi.stubGlobal("fetch", fetchMock);
    const response = await mount.handler(request(mount, false));

    expect(response.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("preserves a backend authorization refusal", async () => {
    const refusal = { error: { code: "FORBIDDEN", message: "Denied", details: null } };
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(Response.json(refusal, { status: 403 })),
    );
    const response = await mount.handler(request(mount));

    expect(response.status).toBe(403);
    expect(await response.json()).toEqual(refusal);
  });
});
