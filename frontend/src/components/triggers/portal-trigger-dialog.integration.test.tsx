import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PortalTriggerDialog } from "./portal-trigger-dialog";
import { apiClient } from "@/lib/api-client";
import type { McpConnectionRecord } from "@/lib/mcp-connections-api";
import type { PortalCatalogEntry } from "@/types/portals";
import { useAgentSelectionStore } from "@/stores";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const GITHUB: PortalCatalogEntry = {
  key: "github",
  name: "GitHub",
  description: "…",
  category: "development",
  icon: "github",
  event_source: "github",
  delivery: "auto_webhook",
  webhook_admin_scopes: ["admin:repo_hook"],
  target_kind: "repo",
  connection_catalog_key: "github",
  presets: [
    { key: "issue_opened", label: "New issue opened", description: "…", target_required: true },
  ],
};

const EMAIL: PortalCatalogEntry = {
  key: "email",
  name: "Email",
  description: "…",
  category: "productivity",
  icon: "gmail",
  event_source: "email",
  delivery: "manual",
  webhook_admin_scopes: [],
  target_kind: null,
  connection_catalog_key: null,
  presets: [
    { key: "any_email", label: "Any incoming email", description: "…", target_required: false },
  ],
};

function connection(): McpConnectionRecord {
  return {
    id: "o1",
    name: "github",
    url: "https://api.githubcopilot.com/mcp/",
    has_auth_token: false,
    allowed_tools: null,
    is_enabled: true,
    auth_type: "oauth",
    oauth_authorized: true,
    last_status: "ok",
    last_error: null,
    last_checked_at: null,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: null,
  };
}

function agent(id: string, name: string, status = "published") {
  return { id, name, status, description: null, has_avatar: false };
}

function serve(targets: { id: string; label: string }[] = []) {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === "/agents") return { items: [agent("a1", "Analyst")], total: 1 };
    if (path.includes("/targets")) return { items: targets, total: targets.length };
    // Any agent's environments and triggers.
    return { items: [], total: 0 };
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  useAgentSelectionStore.getState().setDefault("a1");
});

describe("PortalTriggerDialog", () => {
  it("creates from a preset with the portal payload and no secret", async () => {
    const user = userEvent.setup();
    serve([{ id: "acme/repo", label: "acme/repo" }]);
    vi.mocked(apiClient.post).mockResolvedValue({});
    render(
      <PortalTriggerDialog portal={GITHUB} connection={connection()} open onOpenChange={vi.fn()} />,
      { wrapper },
    );

    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /New issue opened/ }));
    // The target Select is populated from the connected account.
    await user.click(await within(dialog).findByRole("combobox", { name: "Repository" }));
    await user.click(await screen.findByRole("option", { name: "acme/repo" }));
    await user.type(within(dialog).getByLabelText("Message"), "Triage it");
    await user.click(within(dialog).getByRole("button", { name: "Create" }));

    await waitFor(() => expect(apiClient.post).toHaveBeenCalled());
    const [path, payload] = vi.mocked(apiClient.post).mock.calls[0] as [
      string,
      Record<string, unknown>,
    ];
    expect(path).toBe("/agents/a1/triggers");
    expect(payload).toMatchObject({
      prompt: "Triage it",
      trigger_type: "event",
      portal_key: "github",
      preset_key: "issue_opened",
      connection_id: "o1",
      target: "acme/repo",
    });
    // The server mints and seals the secret from the preset; the client sends none.
    expect(payload).not.toHaveProperty("event_secret");
    expect(payload).not.toHaveProperty("event_source");
    expect(payload).not.toHaveProperty("event_config");
  });

  it("falls back to a free-text target when the account lists none", async () => {
    const user = userEvent.setup();
    serve([]);
    render(
      <PortalTriggerDialog portal={GITHUB} connection={connection()} open onOpenChange={vi.fn()} />,
      { wrapper },
    );

    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /New issue opened/ }));

    // No Select, an editable field instead - so a target the listing missed can
    // still be typed.
    expect(within(dialog).queryByRole("combobox", { name: "Repository" })).toBeNull();
    expect(within(dialog).getByPlaceholderText("e.g. owner/repository")).toBeInTheDocument();
  });

  async function createManual(response: Record<string, unknown>) {
    const user = userEvent.setup();
    serve();
    vi.mocked(apiClient.post).mockResolvedValue(response);
    render(<PortalTriggerDialog portal={EMAIL} connection={null} open onOpenChange={vi.fn()} />, {
      wrapper,
    });
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /Any incoming email/ }));
    await user.type(within(dialog).getByLabelText("Message"), "Read it");
    await user.click(within(dialog).getByRole("button", { name: "Create" }));
    return user;
  }

  it("reveals the webhook URL when the result is a manual delivery", async () => {
    await createManual({
      id: "t1",
      trigger_type: "event",
      delivery_mode: "manual",
      webhook_url: "https://api.example.com/api/v1/webhooks/triggers/email/t1",
      reveal_secret: null,
    });

    expect(
      await screen.findByDisplayValue("https://api.example.com/api/v1/webhooks/triggers/email/t1"),
    ).toBeInTheDocument();
    // A manual portal carries no connection, so none is sent.
    const [, payload] = vi.mocked(apiClient.post).mock.calls[0] as [
      string,
      Record<string, unknown>,
    ];
    expect(payload).not.toHaveProperty("connection_id");
  });

  it("reveals the reveal-once signing secret with a copy button when one is returned", async () => {
    const user = await createManual({
      id: "t1",
      trigger_type: "event",
      delivery_mode: "manual",
      webhook_url: "https://api.example.com/api/v1/webhooks/triggers/email/t1",
      reveal_secret: "s3cr3t-sign-me",
    });

    // The secret is shown so the user can wire their relay to sign deliveries.
    expect(await screen.findByLabelText("Signing secret")).toHaveValue("s3cr3t-sign-me");
    expect(screen.getByText(/won't be shown again/)).toBeInTheDocument();

    const copy = vi.fn();
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: copy },
      configurable: true,
    });
    // Two copy buttons now (URL and secret); the secret's is the last.
    const copyButtons = screen.getAllByRole("button", { name: "Copy" });
    await user.click(copyButtons[copyButtons.length - 1] as HTMLElement);
    expect(copy).toHaveBeenCalledWith("s3cr3t-sign-me");
  });

  it("shows no secret field when the manual result carries none", async () => {
    await createManual({
      id: "t1",
      trigger_type: "event",
      delivery_mode: "manual",
      webhook_url: "https://api.example.com/api/v1/webhooks/triggers/email/t1",
      reveal_secret: null,
    });

    await screen.findByDisplayValue("https://api.example.com/api/v1/webhooks/triggers/email/t1");
    expect(screen.queryByLabelText("Signing secret")).toBeNull();
  });
});
