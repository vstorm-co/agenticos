import { beforeEach, describe, expect, it, vi } from "vitest";

import * as personal from "./mcp-connections-api";
import * as org from "./org-mcp-connections-api";
import { apiClient } from "./api-client";

vi.mock("./api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

/**
 * The two MCP connection stores, which are the same shape at different scopes.
 *
 * The distinction is the whole point and it lives in the paths: `/me/…` is a
 * connection one person holds, `/mcp-connections` is one the organization does
 * and an agent may be bound to. Crossing them would let an agent run on
 * somebody's personal credential.
 */
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.get).mockResolvedValue({ items: [{ id: "c-1" }], total: 1 });
  vi.mocked(apiClient.post).mockResolvedValue({ id: "c-1" });
  vi.mocked(apiClient.patch).mockResolvedValue({ id: "c-1" });
  vi.mocked(apiClient.delete).mockResolvedValue(undefined);
});

describe("a person's own connections", () => {
  it("unwraps the list, because no caller wants the envelope", async () => {
    await expect(personal.listMcpConnections()).resolves.toEqual([{ id: "c-1" }]);
    expect(apiClient.get).toHaveBeenCalledWith("/me/mcp-connections");
  });

  it("addresses create, update, delete and test under /me", async () => {
    await personal.createMcpConnection({ name: "Linear", url: "https://mcp.linear.app/sse" });
    expect(apiClient.post).toHaveBeenCalledWith("/me/mcp-connections", {
      name: "Linear",
      url: "https://mcp.linear.app/sse",
    });

    await personal.updateMcpConnection("c-1", { auth_token: "" });
    expect(apiClient.patch).toHaveBeenCalledWith("/me/mcp-connections/c-1", { auth_token: "" });

    await personal.deleteMcpConnection("c-1");
    expect(apiClient.delete).toHaveBeenCalledWith("/me/mcp-connections/c-1");

    await personal.testMcpConnection("c-1");
    expect(apiClient.post).toHaveBeenCalledWith("/me/mcp-connections/c-1/test");
  });
});

describe("starting an OAuth flow", () => {
  it("consents personally by default", async () => {
    await personal.startMcpOAuth({ name: "Linear", url: "https://mcp.linear.app/sse" });

    expect(apiClient.post).toHaveBeenCalledWith("/me/mcp-connections/oauth/start", {
      name: "Linear",
      url: "https://mcp.linear.app/sse",
    });
  });

  it("consents on the organization's behalf when asked, which decides who holds it", async () => {
    // The endpoint is the only thing that differs, and it is what decides whether
    // the returned connection is one agent-bindable by the organization or one
    // person's own.
    await personal.startMcpOAuth(
      { name: "Linear", url: "https://mcp.linear.app/sse" },
      "organization",
    );

    expect(apiClient.post).toHaveBeenCalledWith("/orgs/mcp-connections/oauth/start", {
      name: "Linear",
      url: "https://mcp.linear.app/sse",
    });
  });

  it("starts GitHub through its own org endpoint, keyed by the portal", async () => {
    // GitHub cannot be MCP-discovered, so it has a dedicated endpoint that reads
    // the organization's OAuth App secret rather than a name and URL.
    vi.mocked(apiClient.post).mockResolvedValue({ authorization_url: "https://github/consent" });

    await expect(personal.startGithubOrgOAuth("github")).resolves.toEqual({
      authorization_url: "https://github/consent",
    });
    expect(apiClient.post).toHaveBeenCalledWith("/mcp-connections/oauth/start/github", {
      portal_key: "github",
    });
  });
});

describe("the organization's connections", () => {
  it("unwraps the list from the org-scoped route", async () => {
    await expect(org.listOrgMcpConnections()).resolves.toEqual([{ id: "c-1" }]);
    expect(apiClient.get).toHaveBeenCalledWith("/mcp-connections");
  });

  it("addresses create, update, delete and test without the /me prefix", async () => {
    await org.createOrgMcpConnection({ name: "Linear", url: "https://mcp.linear.app/sse" });
    expect(apiClient.post).toHaveBeenCalledWith("/mcp-connections", {
      name: "Linear",
      url: "https://mcp.linear.app/sse",
    });

    await org.updateOrgMcpConnection("c-1", { is_enabled: false });
    expect(apiClient.patch).toHaveBeenCalledWith("/mcp-connections/c-1", { is_enabled: false });

    await org.deleteOrgMcpConnection("c-1");
    expect(apiClient.delete).toHaveBeenCalledWith("/mcp-connections/c-1");

    await org.testOrgMcpConnection("c-1");
    expect(apiClient.post).toHaveBeenCalledWith("/mcp-connections/c-1/test");
  });
});
