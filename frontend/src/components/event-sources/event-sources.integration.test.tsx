import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState, type ReactNode } from "react";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NodeForm } from "@/components/workflows/property-panel/node-form";
import {
  graph,
  makeCatalog,
  makeDefinition,
  node,
} from "@/components/workflows/validation/fixtures";
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

it.each([
  { setup: "existing dedicated", config: {}, selected: /^Dedicated endpoint/ },
  {
    setup: "new reusable",
    config: { require_source: true },
    selected: /^Select an existing source$/,
  },
])("binds and detaches a reusable source from $setup setup", async ({ config, selected }) => {
  const user = userEvent.setup();
  const definition = makeDefinition({ id: "trigger.webhook", category: "triggers" });
  const catalog = makeCatalog([definition]);
  const update = vi.fn();

  function WebhookForm() {
    const [currentConfig, setConfig] = useState<Record<string, unknown>>(config);
    const entry = node("webhook", definition.id, currentConfig);
    return (
      <NodeForm
        definition={definition}
        node={entry}
        graph={graph({ entry: entry.id, nodes: [entry] })}
        catalog={catalog}
        bindings={[]}
        errors={new Map()}
        updateNodeConfig={(id, next) => {
          update(id, next);
          setConfig(next);
        }}
        upsertBinding={vi.fn()}
        removeBinding={vi.fn()}
      />
    );
  }

  render(<WebhookForm />, { wrapper });
  const picker = screen.getByRole("combobox", { name: "Event source" });
  const warning = screen.getByText(/Anyone who can view this workflow’s runs/);
  expect(warning).toHaveTextContent(/past runs/);
  expect(warning).toHaveTextContent(/does not grant access to the source/);
  await waitFor(() => expect(apiClient.get).toHaveBeenCalledWith("/event-sources"));
  await waitFor(() => expect(picker).toBeEnabled());
  expect(picker).toHaveTextContent(selected);
  expect(update).not.toHaveBeenCalled();
  await user.click(picker);
  await user.click(await screen.findByRole("option", { name: "Issues" }));
  expect(update).toHaveBeenLastCalledWith("webhook", { source_id: "s1" });
  expect(screen.getByDisplayValue(source.webhook_url)).toBeVisible();

  await user.click(picker);
  await user.click(screen.getByRole("option", { name: /^Dedicated endpoint/ }));
  expect(update).toHaveBeenLastCalledWith("webhook", { source_id: null });
  expect(screen.queryByDisplayValue(source.webhook_url)).toBeNull();
});

it("lets an unconfigured webhook explicitly choose a dedicated endpoint even if sources fail to load", async () => {
  const onChange = vi.fn();
  vi.mocked(apiClient.get).mockImplementation(async (path) => {
    if (path === "/event-sources") throw new Error("Sources are unavailable");
    return { permissions: [{ permission: "event_sources:view", scope: "all" }] };
  });
  render(<SourceSelector value={null} onChange={onChange} allowDedicated unconfigured />, {
    wrapper,
  });
  await screen.findByRole("button", { name: "Retry" });
  const picker = screen.getByRole("combobox", { name: "Event source" });
  expect(picker).toHaveTextContent("Select an existing source");
  await userEvent.click(picker);
  await userEvent.click(
    screen.getByRole("option", { name: "Dedicated endpoint (synchronous response)" }),
  );
  expect(onChange).toHaveBeenCalledOnce();
  expect(onChange).toHaveBeenCalledWith(null);
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
    expect(screen.queryByRole("button", { name: "Edit Issues" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Listen to Issues" })).toBeNull();
    expect(
      screen.queryByRole("button", { name: "More actions for Issues" }),
    ).not.toBeInTheDocument();
  });
  it("lets a source user inspect one delivery without a target or editing the source", async () => {
    permissions = ["event_sources:view"];
    items = [{ ...source, can_edit: false, can_use: true }];
    vi.mocked(apiClient.post).mockResolvedValue({ listener_id: "token", expires_at: "later" });
    render(<SourceManager />, { wrapper });
    await userEvent.click(await screen.findByRole("button", { name: "Listen to Issues" }));
    const inspector = within(screen.getByRole("dialog", { name: "Listen to Issues" }));
    expect(screen.queryByRole("button", { name: "Edit Issues" })).toBeNull();
    expect(inspector.queryByText("Or paste example JSON")).toBeNull();
    await userEvent.click(await inspector.findByRole("button", { name: "Listen for event" }));
    expect(await inspector.findByText(/"title": "Broken"/)).toHaveTextContent(
      /"delivery_id": "d1"/,
    );
    expect(apiClient.post).toHaveBeenCalledExactlyOnceWith("/event-sources/s1/listen", {});
    expect(apiClient.patch).not.toHaveBeenCalled();
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
  it("allows an editor to replace an inaccessible binding with a reachable source", async () => {
    const onChange = vi.fn();
    render(<SourceSelector value="unreachable" onChange={onChange} />, { wrapper });
    const picker = screen.getByRole("combobox", { name: "Event source" });
    await waitFor(() => expect(picker).toHaveTextContent("Current source (unavailable)"));
    await userEvent.click(picker);
    expect(screen.getByRole("option", { name: "Current source (unavailable)" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    await userEvent.click(await screen.findByRole("option", { name: "Issues" }));
    expect(onChange).toHaveBeenCalledExactlyOnceWith(source);
  });

  it("leaves the dedicated option available without requesting the source catalog", async () => {
    permissions = [];
    render(<SourceSelector value={null} onChange={vi.fn()} allowDedicated />, { wrapper });
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledWith("/me/permissions"));
    expect(screen.getByRole("combobox", { name: "Event source" })).toBeEnabled();
    expect(apiClient.get).not.toHaveBeenCalledWith("/event-sources");
  });

  it("offers sources beyond the first catalog page", async () => {
    const get = vi.mocked(apiClient.get).getMockImplementation()!;
    vi.mocked(apiClient.get).mockImplementation(async (path, options) => {
      if (path === "/event-sources")
        return {
          items: options ? [{ ...source, id: "later", name: "Second page" }] : [source],
          total: 2,
        };
      return get(path, options);
    });
    const onChange = vi.fn();
    render(<SourceSelector value="later" onChange={onChange} allowDedicated />, { wrapper });
    expect(await screen.findByText("Second page")).toBeVisible();
    expect(apiClient.get).toHaveBeenCalledWith("/event-sources", {
      params: { skip: "1", limit: "100" },
    });
  });

  it("keeps the sources already loaded if the remaining page is empty", async () => {
    const get = vi.mocked(apiClient.get).getMockImplementation()!;
    const list = vi
      .fn()
      .mockResolvedValueOnce({ items: [source], total: 2 })
      .mockResolvedValueOnce({ items: [], total: 1 })
      .mockRejectedValue(new Error("Unexpected extra page"));
    vi.mocked(apiClient.get).mockImplementation(async (path, options) =>
      path === "/event-sources" ? list() : get(path, options),
    );
    render(<SourceManager />, { wrapper });
    expect(await screen.findByRole("heading", { name: "Issues" })).toBeVisible();
    expect(list).toHaveBeenCalledTimes(2);
  });

  it("pauses only the source and explains the subscribers blocking deletion", async () => {
    subscribers = 1;
    render(<SourceManager />, { wrapper });
    expect(await screen.findByText(/Triage/)).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "More actions for Issues" }));
    expect(screen.getByRole("menuitem", { name: "Delete source" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    expect(screen.getByText(/before deleting this source/)).toBeVisible();
    await userEvent.click(screen.getByRole("menuitem", { name: "Pause source" }));
    expect(apiClient.patch).toHaveBeenCalledWith("/event-sources/s1", { is_active: false });
  });

  it("keeps credential replacement open after a refusal and closes it after retry", async () => {
    const user = userEvent.setup();
    vi.mocked(apiClient.post)
      .mockRejectedValueOnce(new Error("Credential replacement refused"))
      .mockResolvedValueOnce(undefined);
    render(<SourceManager />, { wrapper });

    await user.click(await screen.findByRole("button", { name: "More actions for Issues" }));
    await user.click(screen.getByRole("menuitem", { name: "Replace credentials" }));
    const dialog = within(screen.getByRole("dialog", { name: "Replace credentials" }));
    await user.type(dialog.getByLabelText("Secret"), "replacement");
    const submit = dialog.getByRole("button", { name: "Replace credentials" });
    await user.click(submit);
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Credential replacement refused"));
    expect(screen.getByLabelText("Secret")).toHaveValue("replacement");

    await user.click(submit);
    await waitFor(() => expect(screen.queryByLabelText("Secret")).not.toBeInTheDocument());
    expect(apiClient.post).toHaveBeenLastCalledWith("/event-sources/s1/credentials", {
      secret: "replacement",
    });
  });

  it("deletes a source only after confirming and refreshes the catalog", async () => {
    const user = userEvent.setup();
    vi.mocked(apiClient.delete).mockImplementation(async () => {
      items = [];
    });
    render(<SourceManager />, { wrapper });

    await screen.findByText("No subscribers");
    await user.click(screen.getByRole("button", { name: "More actions for Issues" }));
    const deletion = screen.getByRole("menuitem", { name: "Delete source" });
    await user.click(deletion);
    expect(apiClient.delete).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Confirm deletion" }));
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Issues" })).toBeNull());
    expect(apiClient.delete).toHaveBeenCalledExactlyOnceWith("/event-sources/s1");
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
  it.each(["manager", "selector"])(
    "keeps the %s create dialog open until the one-time credential arrives",
    async (entry) => {
      let finish!: () => void;
      vi.mocked(apiClient.post).mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            finish = () => resolve({ ...source, reveal_secret: "once-only" });
          }),
      );
      render(
        entry === "manager" ? (
          <SourceManager />
        ) : (
          <SourceSelector value={null} onChange={vi.fn()} />
        ),
        { wrapper },
      );
      await userEvent.click(await screen.findByRole("button", { name: "Create new source" }));
      const dialog = within(await screen.findByRole("dialog", { name: "Create new source" }));
      await userEvent.type(dialog.getByLabelText("Name"), "Incoming");
      await userEvent.click(dialog.getByRole("button", { name: "Create source" }));
      expect(dialog.getByRole("button", { name: "Cancel" })).toBeDisabled();
      expect(dialog.getByRole("button", { name: "Close" })).toBeDisabled();
      await userEvent.keyboard("{Escape}");
      expect(dialog.getByLabelText("Name")).toBeVisible();
      finish();
      expect(await screen.findByDisplayValue("once-only")).toBeVisible();
    },
  );
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
  it("hides and clears a legacy delivery ID override on Standard Webhooks", async () => {
    render(
      <SourceForm
        source={{
          ...source,
          provider: "webhook",
          auth: { method: "standard_webhooks" },
          delivery_id_header: "X-Old-Delivery-Id",
        }}
        onSaved={vi.fn()}
        onCancel={vi.fn()}
      />,
      { wrapper },
    );
    expect(screen.queryByLabelText("Delivery ID header (optional)")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(apiClient.patch).toHaveBeenCalledWith(
      "/event-sources/s1",
      expect.objectContaining({ delivery_id_header: null }),
    );
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
  it("keeps paste available without offering a listener to a source viewer", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ ...source, can_use: false });
    render(<LiveSample sourceId="s1" onSample={vi.fn()} />, { wrapper });
    expect(await screen.findByText(/Source-use permission is required/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Listen for event" })).toBeNull();
    expect(screen.getByText("Or paste example JSON")).toBeVisible();
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
          resultMode="inbox"
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
        result_mode: "inbox",
      }),
    );
    expect(await screen.findByText("Triage Broken now")).toBeVisible();
  });
});
