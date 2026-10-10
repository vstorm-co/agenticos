import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import { useMcpOAuthOutcome } from "./use-mcp-oauth-outcome";
import { qk } from "@/lib/query-keys";
import { useAddToAgentStore, useOrgStore } from "@/stores";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

/** Land on the page the way the provider's redirect lands on it. */
let client = new QueryClient();

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function arriveAt(query: string) {
  window.history.replaceState({}, "", `/mcp-servers${query}`);
  renderHook(() => useMcpOAuthOutcome(), { wrapper });
}

describe("announcing an MCP OAuth outcome", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    client = new QueryClient();
    useOrgStore.setState({ activeOrgId: "o1" });
    useAddToAgentStore.setState({ offer: null });
  });

  it("names the connection the provider just authorized", () => {
    arriveAt("?mcp_oauth=success&mcp_oauth_name=Linear");

    expect(toast.success).toHaveBeenCalledWith("Linear is connected.");
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("still says it worked when the backend named no connection", () => {
    arriveAt("?mcp_oauth=success&mcp_oauth_name=");

    expect(toast.success).toHaveBeenCalledWith("The server is connected.");
  });

  it("resolves a refusal this repository wrote into the reader's locale", () => {
    arriveAt("?mcp_oauth=error&mcp_oauth_failure=MISSING_AUTHORIZATION_CODE");

    expect(toast.error).toHaveBeenCalledWith("The provider sent no authorization code.");
  });

  it("quotes a provider's own account of a refusal", () => {
    arriveAt("?mcp_oauth=error&mcp_oauth_detail=You%20said%20no");

    expect(toast.error).toHaveBeenCalledWith(
      "Sign-in failed, and no connection was saved — You said no",
    );
  });

  it("strips what it read, so a reload does not announce it again", () => {
    arriveAt("?mcp_oauth=success&mcp_oauth_name=Linear&keep=1");

    expect(window.location.search).toBe("?keep=1");
    renderHook(() => useMcpOAuthOutcome(), { wrapper });
    expect(toast.success).toHaveBeenCalledTimes(1);
  });

  it("says nothing on a page nobody was redirected to", () => {
    arriveAt("");

    expect(toast.success).not.toHaveBeenCalled();
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("offers the organization's server to an agent on its return (#2075)", () => {
    client.setQueryData(qk.organizations.permissions("o1"), {
      permissions: [{ permission: "agents:edit", scope: "all" }],
    });

    arriveAt("?mcp_oauth=success&mcp_oauth_name=Linear&mcp_oauth_connection=c1");

    const [message, options] = vi.mocked(toast.success).mock.calls[0]!;
    expect(message).toBe("Linear is connected.");
    const action = (options as { action: { label: string; onClick: () => void } }).action;
    expect(action.label).toBe("Add to an agent");
    action.onClick();
    expect(useAddToAgentStore.getState().offer).toEqual({
      resource: { kind: "mcp", id: "c1" },
      name: "Linear",
    });
    expect(window.location.search).toBe("");
  });
});
