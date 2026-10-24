import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ConnectOwnButton,
  ConnectOwnServerDialog,
  ConnectServerDialog,
  useConnectEntry,
  useSignInOwn,
} from "./connect-server-dialog";
import { PublicConfigProvider } from "@/components/public-config/public-config-provider";
import { DEFAULT_PUBLIC_CONFIG } from "@/lib/public-config";
import type { McpConnectionRecord } from "@/lib/mcp-connections-api";
import type { McpCatalogEntry } from "@/types/mcp";

const create = vi.fn();
const held = vi.hoisted(() => ({ own: [] as { name: string; catalog_key: string | null }[] }));
vi.mock("@/hooks/use-org-mcp-connections", () => ({
  useOrgMcpConnections: () => ({ create, connections: [] }),
}));
const createOwn = vi.fn();
vi.mock("@/hooks/use-mcp-connections", () => ({
  useMcpConnections: () => ({ create: createOwn, connections: held.own }),
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
    expect(onConnected).toHaveBeenCalledWith(expect.objectContaining({ id: "c9" }));
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
    await userEvent.click(await screen.findByRole("button", { name: "More options" }));
    const name = screen.getByLabelText("Tool prefix");
    await userEvent.clear(name);
    await userEvent.type(name, "Not A Name");

    await submit();

    expect(create).not.toHaveBeenCalled();
    expect(toast.error).toHaveBeenCalled();
  });

  it("refuses a URL that is not http, without calling the API", async () => {
    open(TOKEN_ENTRY);
    await userEvent.click(screen.getByRole("button", { name: "More options" }));
    const url = screen.getByLabelText(/url/i);
    await userEvent.clear(url);
    await userEvent.type(url, "ftp://example.com");

    await submit();

    expect(create).not.toHaveBeenCalled();
    expect(toast.error).toHaveBeenCalled();
  });

  describe("OAuth", () => {
    it("sends a client registered by hand, for a server that registers none itself", async () => {
      // HubSpot publishes no registration endpoint: without these two fields
      // the flow ended at "This server rejected the client registration
      // request" and the server could not be connected from the UI at all.
      vi.spyOn(window, "open").mockReturnValue(null);
      Object.defineProperty(window, "location", {
        configurable: true,
        value: { assign: vi.fn(), origin: "http://forwarded.internal:8443" },
      });
      vi.mocked(startMcpOAuth).mockResolvedValue({ authorization_url: "https://consent" });

      render(
        <PublicConfigProvider
          config={{ ...DEFAULT_PUBLIC_CONFIG, siteUrl: "https://console.example" }}
        >
          <ConnectServerDialog
            entry={{
              ...OAUTH_ENTRY,
              key: "hubspot",
              name: "HubSpot",
              url: "https://mcp.hubspot.com",
            }}
            onClose={vi.fn()}
          />
        </PublicConfigProvider>,
        { wrapper },
      );
      await userEvent.click(await screen.findByRole("button", { name: "More options" }));
      // The redirect URL the provider has to hold, shown so nobody guesses it -
      // built from the deployment's configured origin, which is what the
      // backend registers, not from whatever address this browser came in on.
      expect(
        screen.getByText("https://console.example/api/me/mcp-connections/oauth/callback"),
      ).toBeInTheDocument();
      await userEvent.type(screen.getByLabelText("Client ID"), " app-1 ");
      await userEvent.type(screen.getByLabelText("Client secret"), "shh");
      await submit();

      await waitFor(() =>
        expect(startMcpOAuth).toHaveBeenCalledWith(
          {
            name: "hubspot",
            url: "https://mcp.hubspot.com",
            catalog_key: "hubspot",
            client_id: "app-1",
            client_secret: "shh",
            visibility: "org",
            group_ids: [],
            user_ids: [],
          },
          "organization",
        ),
      );
    });

    it("sends no client when the fields were left empty, so the server registers one", async () => {
      vi.spyOn(window, "open").mockReturnValue(null);
      Object.defineProperty(window, "location", {
        configurable: true,
        value: { assign: vi.fn() },
      });
      vi.mocked(startMcpOAuth).mockResolvedValue({ authorization_url: "https://consent" });

      open(OAUTH_ENTRY);
      await submit();

      await waitFor(() =>
        expect(startMcpOAuth).toHaveBeenCalledWith(
          {
            name: "notion",
            url: "https://mcp.notion.com/mcp",
            catalog_key: "notion",
            visibility: "org",
            group_ids: [],
            user_ids: [],
          },
          "organization",
        ),
      );
    });

    it("refuses a secret typed for a client nobody named, without calling the API", async () => {
      // The backend answers 422 to that; the dialog says why before the trip.
      const openSpy = vi.spyOn(window, "open").mockReturnValue(null);

      open(OAUTH_ENTRY);
      await userEvent.click(await screen.findByRole("button", { name: "More options" }));
      await userEvent.type(screen.getByLabelText("Client secret"), "shh");
      await submit();

      expect(startMcpOAuth).not.toHaveBeenCalled();
      expect(openSpy).not.toHaveBeenCalled();
      expect(toast.error).toHaveBeenCalledWith(
        "A client secret needs the client ID it belongs to.",
      );
    });

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

    it("lands the other tab on the server's accounts and refetches here on return", async () => {
      const tab = { location: { href: "" }, close: vi.fn() };
      const openSpy = vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);
      const invalidate = vi.spyOn(QueryClient.prototype, "invalidateQueries");
      vi.mocked(startMcpOAuth).mockResolvedValue({ authorization_url: "https://consent" });
      // An earlier test's consent left its own one-shot listener waiting.
      window.dispatchEvent(new Event("focus"));
      invalidate.mockClear();

      open(OAUTH_ENTRY);
      await submit();

      await waitFor(() => expect(tab.location.href).toBe("https://consent"));
      expect(document.cookie).toContain(
        `mcp_oauth_return=${encodeURIComponent("/mcp-servers?server=notion")}`,
      );
      expect(invalidate).not.toHaveBeenCalled();
      window.dispatchEvent(new Event("focus"));
      window.dispatchEvent(new Event("focus"));
      // Once, on the first return: the listener goes with it.
      expect(invalidate).toHaveBeenCalledTimes(1);
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ["mcp-connections"] });
      invalidate.mockRestore();
      openSpy.mockRestore();
    });

    it("asks for a tab it can still write to, and severs the opener itself", async () => {
      // `window.open(..., "noopener")` returns null in a browser that
      // implements the feature, even though the tab was created - so the
      // success path read that as blocked, navigated the Builder itself, and
      // discarded the unsaved draft this dialog exists to preserve.
      const tab = { location: { href: "" }, close: vi.fn(), opener: {} as unknown };
      const openSpy = vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);
      vi.mocked(startMcpOAuth).mockResolvedValue({ authorization_url: "https://consent" });

      open(OAUTH_ENTRY);
      await submit();

      await waitFor(() => expect(tab.location.href).toBe("https://consent"));
      expect(openSpy).toHaveBeenCalledWith("", "_blank");
      expect(tab.opener).toBeNull();
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

describe("ConnectOwnServerDialog", () => {
  /**
   * The same form on the personal scope - what a chat opens when an agent bound
   * to each person's own account finds this person has none. The catalog key is
   * the whole point: a personal connection without one can never be matched to
   * the binding that asked for it.
   */
  beforeEach(() => {
    vi.clearAllMocks();
    createOwn.mockResolvedValue({ id: "m9", name: "github" });
  });

  it("creates the person's own connection, carrying the catalog key", async () => {
    const onConnected = vi.fn();
    render(
      <ConnectOwnServerDialog entry={TOKEN_ENTRY} onClose={vi.fn()} onConnected={onConnected} />,
      {
        wrapper,
      },
    );

    await submit();

    await waitFor(() =>
      expect(createOwn).toHaveBeenCalledWith(expect.objectContaining({ catalog_key: "github" })),
    );
    expect(create).not.toHaveBeenCalled();
    expect(onConnected).toHaveBeenCalledWith(expect.objectContaining({ id: "m9" }));
    expect(toast.success).toHaveBeenCalledWith(expect.stringMatching(/for you/i));
  });

  it("starts OAuth on the personal scope, with the catalog key", async () => {
    vi.mocked(startMcpOAuth).mockResolvedValue({ authorization_url: "https://consent.example" });
    const opened = { location: { href: "" }, opener: {}, close: vi.fn() };
    vi.spyOn(window, "open").mockReturnValue(opened as unknown as Window);
    render(<ConnectOwnServerDialog entry={OAUTH_ENTRY} onClose={vi.fn()} />, { wrapper });

    await submit();

    await waitFor(() =>
      expect(startMcpOAuth).toHaveBeenCalledWith(
        { name: "notion", url: "https://mcp.notion.com/mcp", catalog_key: "notion" },
        "personal",
      ),
    );
    expect(opened.location.href).toBe("https://consent.example");
  });

  it("renders nothing until an entry is chosen", () => {
    render(<ConnectOwnServerDialog entry={null} onClose={vi.fn()} />, { wrapper });

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("says the tab was blocked rather than leave a tab it was told to keep", async () => {
    // A chat run paused until this connection is made is held by this tab's
    // socket; navigating away would answer it as a skip.
    const openSpy = vi.spyOn(window, "open").mockReturnValue(null);
    const assign = vi.fn();
    Object.defineProperty(window, "location", { configurable: true, value: { assign } });
    render(<ConnectOwnServerDialog entry={OAUTH_ENTRY} onClose={vi.fn()} keepThisTab />, {
      wrapper,
    });

    await submit();

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "Your browser blocked the sign-in tab. Allow pop-ups for this site, then try again.",
      ),
    );
    expect(startMcpOAuth).not.toHaveBeenCalled();
    expect(assign).not.toHaveBeenCalled();
    openSpy.mockRestore();
  });
});

describe("ConnectOwnServerDialog with somewhere to return to", () => {
  it("runs the consent in this tab and remembers the way back", async () => {
    // A chat has nothing unsaved to lose and a conversation to come back to, so
    // the new-tab dance the Builder needs would only leave the person on the
    // servers page with a toast and no way back but the history.
    vi.clearAllMocks();
    vi.mocked(startMcpOAuth).mockResolvedValue({ authorization_url: "https://consent.example" });
    const opened = vi.spyOn(window, "open");
    render(<ConnectOwnServerDialog entry={OAUTH_ENTRY} onClose={vi.fn()} returnTo="/chat?id=1" />, {
      wrapper,
    });

    await submit();

    await waitFor(() => expect(startMcpOAuth).toHaveBeenCalled());
    expect(opened).not.toHaveBeenCalled();
    expect(document.cookie).toContain(`mcp_oauth_return=${encodeURIComponent("/chat?id=1")}`);
    expect(toast.info).not.toHaveBeenCalled();
  });
});

describe("ConnectOwnButton", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(startMcpOAuth).mockResolvedValue({ authorization_url: "https://consent.example" });
  });

  it("goes straight to the provider for a server that signs in, with no form", async () => {
    const tab = { opener: {}, location: { href: "" }, close: vi.fn() };
    const opened = vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);
    render(<ConnectOwnButton entry={OAUTH_ENTRY} label="Connect" />, { wrapper });

    await userEvent.click(screen.getByRole("button", { name: "Connect" }));

    await waitFor(() =>
      expect(startMcpOAuth).toHaveBeenCalledWith(
        { name: "notion", url: "https://mcp.notion.com/mcp", catalog_key: "notion" },
        "personal",
      ),
    );
    expect(tab.location.href).toBe("https://consent.example");
    expect(tab.opener).toBeNull();
    expect(screen.queryByRole("dialog")).toBeNull();
    opened.mockRestore();
  });

  it("closes the tab and says so when the consent cannot start", async () => {
    const tab = { opener: {}, location: { href: "" }, close: vi.fn() };
    const opened = vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);
    vi.mocked(startMcpOAuth).mockRejectedValue(new Error("down"));
    render(<ConnectOwnButton entry={OAUTH_ENTRY} label="Connect" />, { wrapper });

    await userEvent.click(screen.getByRole("button", { name: "Connect" }));

    await waitFor(() => expect(tab.close).toHaveBeenCalled());
    expect(toast.error).toHaveBeenCalled();
    opened.mockRestore();
  });

  it("opens the form for a server that takes a token, and offers no Configure", async () => {
    render(<ConnectOwnButton entry={TOKEN_ENTRY} label="Connect" />, { wrapper });

    expect(screen.queryByRole("button", { name: /^Configure/ })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Connect" }));

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(startMcpOAuth).not.toHaveBeenCalled();
  });

  it("opens the form on Configure with its settings folded, and closes it", async () => {
    render(<ConnectOwnButton entry={OAUTH_ENTRY} label="Connect" />, { wrapper });

    await userEvent.click(
      screen.getByRole("button", { name: "Configure Notion before connecting" }),
    );
    expect(screen.queryByLabelText("Server URL")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "More options" }));
    expect(await screen.findByLabelText("Server URL")).toHaveValue("https://mcp.notion.com/mcp");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});

describe("useConnectEntry for the organization", () => {
  function Harness({ entry, openForm }: { entry: McpCatalogEntry; openForm: () => void }) {
    const connect = useConnectEntry("organization", { openForm });
    return (
      <button type="button" onClick={() => connect(entry)}>
        go
      </button>
    );
  }

  it("signs in for everyone in the organization, the form's own default", async () => {
    vi.clearAllMocks();
    vi.mocked(startMcpOAuth).mockResolvedValue({ authorization_url: "https://consent.example" });
    const tab = { opener: {}, location: { href: "" }, close: vi.fn() };
    const opened = vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);
    render(<Harness entry={OAUTH_ENTRY} openForm={vi.fn()} />, { wrapper });

    await userEvent.click(screen.getByRole("button", { name: "go" }));

    await waitFor(() =>
      expect(startMcpOAuth).toHaveBeenCalledWith(
        expect.objectContaining({ visibility: "org", group_ids: [], user_ids: [] }),
        "organization",
      ),
    );
    expect(toast.info).toHaveBeenCalled();
    opened.mockRestore();
  });

  it("opens the form for a catalog server with no address on record", async () => {
    const openForm = vi.fn();
    render(<Harness entry={{ ...OAUTH_ENTRY, url: null }} openForm={openForm} />, { wrapper });

    await userEvent.click(screen.getByRole("button", { name: "go" }));

    expect(openForm).toHaveBeenCalled();
  });
});

describe("useConnectEntry with names already taken", () => {
  it("signs in under the first free prefix", async () => {
    vi.clearAllMocks();
    vi.mocked(startMcpOAuth).mockResolvedValue({ authorization_url: "https://consent.example" });
    function Harness() {
      // Taken by other services' accounts: the names are the prefixes to avoid.
      const connect = useConnectEntry("personal", {
        openForm: vi.fn(),
        returnTo: "/agents/a1",
        held: [
          { name: "notion", catalog_key: null },
          { name: "notion-2", catalog_key: "notion-clone" },
        ],
      });
      return (
        <button type="button" onClick={() => connect(OAUTH_ENTRY)}>
          go
        </button>
      );
    }
    render(<Harness />, { wrapper });

    await userEvent.click(screen.getByRole("button", { name: "go" }));

    await waitFor(() =>
      expect(startMcpOAuth).toHaveBeenCalledWith(
        expect.objectContaining({ name: "notion-3" }),
        "personal",
      ),
    );
  });
});

describe("a second account on one service", () => {
  it("goes through the form, where it is named, rather than straight to consent", async () => {
    vi.clearAllMocks();
    const openForm = vi.fn();
    function Harness() {
      const connect = useConnectEntry("personal", {
        openForm,
        returnTo: "/agents/a1",
        held: [{ name: "notion", catalog_key: "notion" }],
      });
      return (
        <button type="button" onClick={() => connect(OAUTH_ENTRY)}>
          go
        </button>
      );
    }
    render(<Harness />, { wrapper });

    await userEvent.click(screen.getByRole("button", { name: "go" }));

    expect(openForm).toHaveBeenCalledWith(OAUTH_ENTRY);
    expect(startMcpOAuth).not.toHaveBeenCalled();
  });

  it("asks for a name before consent, then carries it under a free prefix", async () => {
    vi.clearAllMocks();
    held.own = [{ name: "notion", catalog_key: "notion" }];
    vi.mocked(startMcpOAuth).mockResolvedValue({ authorization_url: "https://consent.example" });
    render(<ConnectOwnServerDialog entry={OAUTH_ENTRY} onClose={vi.fn()} returnTo="/agents/a1" />, {
      wrapper,
    });

    await userEvent.click(screen.getByRole("button", { name: /Connect/ }));
    expect(startMcpOAuth).not.toHaveBeenCalled();
    expect(screen.getByText(/already have an account on this service/)).toBeInTheDocument();

    await userEvent.type(screen.getByRole("textbox", { name: "Name" }), "Work");
    await userEvent.click(screen.getByRole("button", { name: /Connect/ }));

    await waitFor(() =>
      expect(startMcpOAuth).toHaveBeenCalledWith(
        expect.objectContaining({ name: "notion-2", label: "Work", catalog_key: "notion" }),
        "personal",
      ),
    );
    held.own = [];
  });
});

describe("useSignInOwn", () => {
  function Harness({ connection }: { connection: McpConnectionRecord }) {
    const signIn = useSignInOwn({ returnTo: "/agents/a1" });
    return (
      <button type="button" onClick={() => signIn(connection)}>
        go
      </button>
    );
  }

  it("signs an account in again under the name it has", async () => {
    vi.clearAllMocks();
    vi.mocked(startMcpOAuth).mockResolvedValue({ authorization_url: "https://consent.example" });
    const lapsed = {
      id: "p2",
      name: "notion-2",
      url: "https://mcp.notion.com/mcp",
      catalog_key: "notion",
    } as McpConnectionRecord;
    const { rerender } = render(<Harness connection={lapsed} />, { wrapper });

    await userEvent.click(screen.getByRole("button", { name: "go" }));
    await waitFor(() =>
      expect(startMcpOAuth).toHaveBeenCalledWith(
        { name: "notion-2", url: "https://mcp.notion.com/mcp", catalog_key: "notion" },
        "personal",
      ),
    );

    // One added by its address has no catalog key to send.
    rerender(<Harness connection={{ ...lapsed, name: "crm", catalog_key: null }} />);
    await userEvent.click(screen.getByRole("button", { name: "go" }));
    await waitFor(() =>
      expect(startMcpOAuth).toHaveBeenLastCalledWith(
        { name: "crm", url: "https://mcp.notion.com/mcp" },
        "personal",
      ),
    );
  });

  it("names no page to come back to for a server outside the catalog, from another tab", async () => {
    function NewTab({ connection }: { connection: McpConnectionRecord }) {
      const signIn = useSignInOwn({});
      return (
        <button type="button" onClick={() => signIn(connection)}>
          go
        </button>
      );
    }
    vi.mocked(startMcpOAuth).mockResolvedValue({ authorization_url: "https://consent.example" });
    const tab = { location: { href: "" }, close: vi.fn() };
    const openSpy = vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);
    document.cookie = "mcp_oauth_return=; path=/; max-age=0";
    const custom = { id: "p3", name: "crm", url: "https://crm.example/mcp", catalog_key: null };
    render(<NewTab connection={custom as McpConnectionRecord} />, { wrapper });

    await userEvent.click(screen.getByRole("button", { name: "go" }));
    await waitFor(() => expect(tab.location.href).toBe("https://consent.example"));
    expect(document.cookie).not.toContain("mcp_oauth_return=");
    openSpy.mockRestore();
  });
});
