import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConnectServerDialog } from "./connect-server-dialog";
import type { McpCatalogEntry } from "@/types/mcp";

const create = vi.fn();
vi.mock("@/hooks/use-org-mcp-connections", () => ({
  useOrgMcpConnections: () => ({ create }),
}));
vi.mock("@/lib/mcp-connections-api", () => ({ startMcpOAuth: vi.fn() }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));

import { startMcpOAuth } from "@/lib/mcp-connections-api";
import { toast } from "sonner";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const TOKEN_ENTRY: McpCatalogEntry = {
  key: "github",
  name: "GitHub",
  description: "Read issues and pull requests.",
  category: "development",
  auth: "token",
  url: "https://api.githubcopilot.com/mcp/",
  docs_url: null,
  token_hint: null,
  icon: null,
};

const OAUTH_ENTRY: McpCatalogEntry = {
  ...TOKEN_ENTRY,
  key: "notion",
  name: "Notion",
  auth: "oauth",
  url: "https://mcp.notion.com/mcp",
};

function open(entry: McpCatalogEntry, onConnected = vi.fn(), onClose = vi.fn()) {
  render(<ConnectServerDialog entry={entry} onClose={onClose} onConnected={onConnected} />, {
    wrapper,
  });
  return { onConnected, onClose };
}

/** The dialog seeds its own name from the entry; submit is the form's button. */
async function submit() {
  await userEvent.click(screen.getByRole("button", { name: /connect/i }));
}

describe("ConnectServerDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    create.mockResolvedValue({ id: "c9", name: "github" });
  });

  it("renders nothing until an entry is chosen", () => {
    render(<ConnectServerDialog entry={null} onClose={vi.fn()} />, { wrapper });

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("creates the organization's connection and hands back its id to bind", async () => {
    const { onConnected, onClose } = open(TOKEN_ENTRY);

    await submit();

    await waitFor(() =>
      expect(create).toHaveBeenCalledWith(
        expect.objectContaining({
          url: "https://api.githubcopilot.com/mcp/",
          // Provenance, so the picker groups it under the entry it came from.
          catalog_key: "github",
        }),
      ),
    );
    expect(onConnected).toHaveBeenCalledWith("c9");
    expect(onClose).toHaveBeenCalled();
  });

  it("surfaces a refusal and leaves the dialog open", async () => {
    create.mockRejectedValue(new Error("nope"));
    const { onConnected, onClose } = open(TOKEN_ENTRY);

    await submit();

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(onConnected).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("sends no token for a server that needs none", async () => {
    // Switching away from a token must not quietly store whatever was typed.
    open({ ...TOKEN_ENTRY, key: "cloudflare-docs", name: "Cloudflare docs", auth: "none" });

    await submit();

    await waitFor(() =>
      expect(create).toHaveBeenCalledWith(expect.objectContaining({ auth_token: undefined })),
    );
  });

  it("refuses a name the server would not accept, without calling the API", async () => {
    open(TOKEN_ENTRY);
    // Exact: the form has a display name too, and /name/i matches both.
    const name = screen.getByLabelText("Name");
    await userEvent.clear(name);
    await userEvent.type(name, "Not A Name");

    await submit();

    expect(create).not.toHaveBeenCalled();
    expect(toast.error).toHaveBeenCalled();
  });

  it("refuses a URL that is not http, without calling the API", async () => {
    open(TOKEN_ENTRY);
    const url = screen.getByLabelText(/url/i);
    await userEvent.clear(url);
    await userEvent.type(url, "ftp://example.com");

    await submit();

    expect(create).not.toHaveBeenCalled();
    expect(toast.error).toHaveBeenCalled();
  });

  describe("OAuth", () => {
    it("opens the tab on the click, before the request that produces the URL", async () => {
      // Opened inside the await's callback, a popup blocker treats it as
      // unprompted. So the tab exists first and is pointed at the URL after.
      const tab = { location: { href: "" }, close: vi.fn() };
      const openSpy = vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);
      vi.mocked(startMcpOAuth).mockResolvedValue({ authorization_url: "https://consent" });

      open(OAUTH_ENTRY);
      await submit();

      await waitFor(() => expect(tab.location.href).toBe("https://consent"));
      expect(openSpy).toHaveBeenCalledBefore(vi.mocked(startMcpOAuth));
      // The organization's, never the caller's own - a personal connection is
      // refused at publish.
      expect(startMcpOAuth).toHaveBeenCalledWith(expect.anything(), "organization");
      expect(create).not.toHaveBeenCalled();
      openSpy.mockRestore();
    });

    it("navigates in place when the tab was blocked anyway", async () => {
      const openSpy = vi.spyOn(window, "open").mockReturnValue(null);
      vi.mocked(startMcpOAuth).mockResolvedValue({ authorization_url: "https://consent" });
      const assign = vi.fn();
      Object.defineProperty(window, "location", {
        configurable: true,
        value: { assign },
      });

      open(OAUTH_ENTRY);
      await submit();

      await waitFor(() => expect(assign).toHaveBeenCalledWith("https://consent"));
      openSpy.mockRestore();
    });

    it("closes the tab it opened when consent could not be started", async () => {
      const tab = { location: { href: "" }, close: vi.fn() };
      const openSpy = vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);
      vi.mocked(startMcpOAuth).mockRejectedValue(new Error("down"));

      open(OAUTH_ENTRY);
      await submit();

      await waitFor(() => expect(tab.close).toHaveBeenCalled());
      expect(toast.error).toHaveBeenCalled();
      openSpy.mockRestore();
    });
  });
});
