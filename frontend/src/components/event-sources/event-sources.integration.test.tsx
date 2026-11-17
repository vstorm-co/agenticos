import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "@/lib/api-client";
import type { EventSource } from "@/lib/event-sources-api";
import { SourceForm } from "./source-form";
import { SourceManager } from "./source-manager";
import { SourceSelector } from "./source-selector";
import { RoutinePrompt } from "./routine-prompt";
import { LiveSample, PasteSample } from "./live-sample";

vi.mock("@/lib/api-client", async () => ({
  ...(await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client")),
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
const source: EventSource = {
  id: "s1",
  name: "Issues",
  provider: "github",
  auth: { method: "provider" },
  visibility: "private",
  owner_user_id: "u1",
  delivery_id_header: null,
  is_active: true,
  webhook_url: "https://example.test/api/v1/webhooks/sources/s1",
  can_use: true,
  can_edit: true,
};
let permissions: string[];
let items: EventSource[];
let subscribers = 0;
function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
        })
      }
    >
      {children}
    </QueryClientProvider>
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  permissions = ["event_sources:view", "event_sources:use", "event_sources:edit"];
  items = [source];
  subscribers = 0;
  vi.mocked(apiClient.get).mockImplementation(async (path) => {
    if (path === "/me/permissions")
      return { permissions: permissions.map((permission) => ({ permission, scope: "all" })) };
    if (path === "/event-sources") return { items, total: items.length };
    if (path.endsWith("/usage"))
      return {
        items: subscribers
          ? [{ id: "sub1", kind: "routine", target_id: "r1", name: "Triage", is_active: true }]
          : [],
        total: subscribers,
      };
    if (path.includes("/listen/"))
      return {
        state: "caught",
        delivery: { body: { issue: { title: "Broken" } }, delivery_id: "d1" },
      };
    return source;
  });
  vi.mocked(apiClient.post).mockResolvedValue({ ...source, reveal_secret: "once-only" });
  vi.mocked(apiClient.patch).mockResolvedValue(source);
});

describe("event source management", () => {
  it("waits for permissions before claiming source access is refused", () => {
    vi.mocked(apiClient.get).mockImplementation(() => new Promise(() => {}));
    render(<SourceManager />, { wrapper });
    expect(screen.queryByText("You do not have permission to view event sources.")).toBeNull();
    expect(screen.queryByRole("button", { name: "Create new source" })).toBeNull();
  });

  it("renders real sources and hides edits without resource authority", async () => {
    permissions = ["event_sources:view"];
    items = [{ ...source, can_edit: false, can_use: false }];
    render(<SourceManager />, { wrapper });
    expect(await screen.findByText("Issues")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Create new source" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete source" })).not.toBeInTheDocument();
  });
  it("keeps the current source visible after use permission is revoked", async () => {
    permissions = ["event_sources:view"];
    items = [{ ...source, can_use: false, can_edit: false }];
    const onChange = vi.fn();
    render(<SourceSelector value="s1" onChange={onChange} />, { wrapper });
    expect(await screen.findByText("Issues")).toBeVisible();
    await userEvent.click(screen.getByRole("combobox", { name: "Event source" }));
    expect(screen.getByRole("option", { name: "Issues" })).toHaveAttribute("aria-disabled", "true");
    expect(onChange).not.toHaveBeenCalled();
  });

  it("pauses only the source and explains the subscribers blocking deletion", async () => {
    subscribers = 1;
    render(<SourceManager />, { wrapper });
    expect(await screen.findByText(/Triage/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Delete source" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Pause source" }));
    expect(apiClient.patch).toHaveBeenCalledWith("/event-sources/s1", { is_active: false });
  });
  it("creates a private HMAC source and reveals its generated secret only in creation state", async () => {
    render(<SourceSelector value={null} onChange={vi.fn()} />, { wrapper });
    await userEvent.click(await screen.findByRole("button", { name: "Create new source" }));
    await userEvent.type(screen.getByLabelText("Name"), "Incoming");
    await userEvent.click(screen.getByRole("button", { name: "Create source" }));
    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith(
        "/event-sources",
        expect.objectContaining({
          name: "Incoming",
          provider: "webhook",
          visibility: "private",
          credentials: {},
          auth: expect.objectContaining({ method: "hmac" }),
        }),
      ),
    );
    expect(await screen.findByDisplayValue("once-only")).toBeVisible();
  });
  it("distinguishes a failed read from an empty list", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path) => {
      if (path === "/me/permissions")
        return { permissions: permissions.map((permission) => ({ permission })) };
      throw new Error("Unavailable");
    });
    render(<SourceManager />, { wrapper });
    expect(await screen.findByText("Event sources could not be loaded.")).toBeVisible();
    expect(screen.queryByText(/No event sources yet/)).not.toBeInTheDocument();
  });
});

describe("source authentication form", () => {
  it.each(["GitHub", "Linear", "HubSpot", "Zendesk"])(
    "keeps %s provider verification separate from custom authentication",
    async (provider) => {
      render(<SourceForm onSaved={vi.fn()} onCancel={vi.fn()} />, { wrapper });
      await userEvent.type(screen.getByLabelText("Name"), "Events");
      await userEvent.click(screen.getByRole("combobox", { name: "Provider" }));
      await userEvent.click(screen.getByRole("option", { name: provider }));
      expect(screen.queryByRole("combobox", { name: "Authentication" })).toBeNull();
      expect(screen.getByRole("button", { name: "Create source" })).toBeDisabled();
      await userEvent.type(screen.getByLabelText("Secret"), "provider-secret");
      await userEvent.click(screen.getByRole("button", { name: "Create source" }));
      expect(apiClient.post).toHaveBeenCalledWith(
        "/event-sources",
        expect.objectContaining({
          provider: provider.toLowerCase(),
          auth: { method: "provider" },
          credentials: { secret: "provider-secret" },
        }),
      );
    },
  );
  it("submits Basic Auth credentials only in the source creation request", async () => {
    render(<SourceForm onSaved={vi.fn()} onCancel={vi.fn()} />, { wrapper });
    await userEvent.type(screen.getByLabelText("Name"), "Basic");
    await userEvent.click(screen.getByRole("combobox", { name: "Authentication" }));
    await userEvent.click(screen.getByRole("option", { name: "Basic Auth" }));
    await userEvent.type(screen.getByLabelText("Username"), "sender");
    await userEvent.type(screen.getByLabelText("Password"), "password");
    await userEvent.click(screen.getByRole("button", { name: "Create source" }));
    expect(apiClient.post).toHaveBeenCalledWith(
      "/event-sources",
      expect.objectContaining({
        auth: { method: "basic" },
        credentials: { username: "sender", password: "password" },
      }),
    );
  });
  it.each([
    ["API Key", "api_key"],
    ["Standard Webhooks", "standard_webhooks"],
  ])("submits %s authentication without reusing HMAC settings", async (label, method) => {
    render(<SourceForm onSaved={vi.fn()} onCancel={vi.fn()} />, { wrapper });
    await userEvent.type(screen.getByLabelText("Name"), "Events");
    await userEvent.click(screen.getByRole("combobox", { name: "Authentication" }));
    await userEvent.click(screen.getByRole("option", { name: label }));
    if (method === "api_key")
      expect(screen.getByLabelText("Signature or key prefix (optional)")).toHaveValue("");
    await userEvent.click(screen.getByRole("button", { name: "Create source" }));
    expect(apiClient.post).toHaveBeenCalledWith(
      "/event-sources",
      expect.objectContaining({
        auth:
          method === "api_key"
            ? { method, header_name: "X-API-Key", signature_prefix: "" }
            : { method },
      }),
    );
  });
  it("edits signing settings without copying stored credentials", async () => {
    render(
      <SourceForm
        source={{
          ...source,
          provider: "webhook",
          auth: {
            method: "hmac",
            header_name: "X-Signature",
            signature_prefix: "sha256=",
            encoding: "hex",
          },
        }}
        onSaved={vi.fn()}
        onCancel={vi.fn()}
      />,
      { wrapper },
    );
    expect(screen.queryByLabelText("Secret")).toBeNull();
    fireEvent.change(screen.getByLabelText("Header name"), { target: { value: "X-Changed" } });
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(apiClient.patch).toHaveBeenCalledWith(
      "/event-sources/s1",
      expect.objectContaining({ auth: expect.objectContaining({ header_name: "X-Changed" }) }),
    );
    expect(vi.mocked(apiClient.patch).mock.calls[0]?.[1]).not.toHaveProperty("credentials");
  });
});

describe("editor samples", () => {
  it("listens on the existing URL and returns the JSON output shape without executing anything", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({
      listener_id: "listen-token",
      expires_at: "later",
    });
    const onSample = vi.fn();
    render(<LiveSample sourceId="s1" onSample={onSample} />, { wrapper });
    expect(await screen.findByDisplayValue(source.webhook_url)).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Listen for event" }));
    await waitFor(() =>
      expect(onSample).toHaveBeenCalledWith({
        body: { issue: { title: "Broken" } },
        delivery_id: "d1",
      }),
    );
    expect(apiClient.post).toHaveBeenCalledExactlyOnceWith("/event-sources/s1/listen", {});
    expect(screen.getByText(/Active subscribers still execute/)).toBeVisible();
  });
  it("refuses non-object JSON and accepts falsy payload values without an API request", async () => {
    const onSample = vi.fn();
    render(<PasteSample onSample={onSample} />);
    fireEvent.change(screen.getByLabelText("Example JSON object"), { target: { value: "[]" } });
    await userEvent.click(screen.getByRole("button", { name: "Use example", hidden: true }));
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a valid JSON object.");
    fireEvent.change(screen.getByLabelText("Example JSON object"), {
      target: { value: '{"zero":0,"no":false,"empty":null}' },
    });
    await userEvent.click(screen.getByRole("button", { name: "Use example", hidden: true }));
    expect(onSample).toHaveBeenCalledWith({
      body: { zero: 0, no: false, empty: null },
      delivery_id: "example",
    });
    expect(apiClient.post).not.toHaveBeenCalled();
  });
  it("inserts a selected field at the prompt cursor and uses only the backend preview operation", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ resolved_prompt: "Triage Broken now" });
    function Editor() {
      const [value, setValue] = useState("Triage  now");
      return (
        <RoutinePrompt
          value={value}
          onChange={setValue}
          mode="template"
          onModeChange={vi.fn()}
          sourceId={null}
          agentId="a1"
        />
      );
    }
    render(<Editor />, { wrapper });
    fireEvent.change(screen.getByLabelText("Example JSON object"), {
      target: { value: '{"issue":{"title":"Broken"}}' },
    });
    await userEvent.click(screen.getByRole("button", { name: "Use example", hidden: true }));
    const prompt = screen.getByLabelText("Message") as HTMLTextAreaElement;
    prompt.setSelectionRange(7, 7);
    await userEvent.click(screen.getByRole("button", { name: /\{\{issue.title\}\}/ }));
    expect(prompt).toHaveValue("Triage {{issue.title}} now");
    await userEvent.click(screen.getByRole("button", { name: "Preview resolved prompt" }));
    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledExactlyOnceWith("/agents/a1/triggers/preview-prompt", {
        prompt: "Triage {{issue.title}} now",
        payload: { issue: { title: "Broken" } },
      }),
    );
    expect(await screen.findByText("Triage Broken now")).toBeVisible();
  });
});
