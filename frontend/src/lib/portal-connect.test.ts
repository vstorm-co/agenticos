import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  startGithubOrgOAuth,
  startMcpOAuth,
  startPolledPortalOAuth,
} from "@/lib/mcp-connections-api";

import { portalConnectUrl } from "./portal-connect";

vi.mock("@/lib/mcp-connections-api", () => ({
  startGithubOrgOAuth: vi.fn().mockResolvedValue({ authorization_url: "https://github/consent" }),
  startMcpOAuth: vi.fn().mockResolvedValue({ authorization_url: "https://mcp/consent" }),
  startPolledPortalOAuth: vi
    .fn()
    .mockResolvedValue({ authorization_url: "https://google/consent" }),
}));

const portal = (overrides: Record<string, unknown>) => ({
  portal: { key: "x", name: "X", delivery: "auto_webhook", event_source: "webhook", ...overrides },
  serverName: null,
  serverUrl: null,
});

beforeEach(() => vi.clearAllMocks());

describe("portalConnectUrl", () => {
  it("connects a polled mailbox on the deployment's own client", async () => {
    const url = await portalConnectUrl(portal({ key: "google", delivery: "polling" }) as never);
    expect(url).toBe("https://google/consent");
    expect(startPolledPortalOAuth).toHaveBeenCalledWith("google");
  });

  it("connects GitHub on the organization's OAuth App", async () => {
    const url = await portalConnectUrl(portal({ key: "github", event_source: "github" }) as never);
    expect(url).toBe("https://github/consent");
    expect(startGithubOrgOAuth).toHaveBeenCalledWith("github");
  });

  it("connects anything else by discovery, under its server's name or the portal's", async () => {
    await portalConnectUrl({
      ...portal({}),
      serverName: "Linear",
      serverUrl: "https://l",
    } as never);
    await portalConnectUrl(portal({ name: "Notion" }) as never);
    expect(vi.mocked(startMcpOAuth).mock.calls).toEqual([
      [{ name: "Linear", url: "https://l" }, "organization"],
      [{ name: "Notion", url: "" }, "organization"],
    ]);
  });
});
