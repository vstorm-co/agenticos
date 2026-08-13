import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import { useMcpOAuthOutcome } from "./use-mcp-oauth-outcome";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

/** Land on the page the way the provider's redirect lands on it. */
function arriveAt(query: string) {
  window.history.replaceState({}, "", `/mcp-servers${query}`);
  renderHook(() => useMcpOAuthOutcome());
}

describe("announcing an MCP OAuth outcome", () => {
  beforeEach(() => {
    vi.clearAllMocks();
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
    renderHook(() => useMcpOAuthOutcome());
    expect(toast.success).toHaveBeenCalledTimes(1);
  });

  it("says nothing on a page nobody was redirected to", () => {
    arriveAt("");

    expect(toast.success).not.toHaveBeenCalled();
    expect(toast.error).not.toHaveBeenCalled();
  });
});
