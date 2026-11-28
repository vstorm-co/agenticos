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
import type {
  EventSource,
  EventSourceDelivery,
  EventSourceDeliveryDetail,
  SourceUsage,
} from "@/lib/event-sources-api";
import { SourceForm } from "./source-form";
import { SourceManager } from "./source-manager";
import { SourceSelector } from "./source-selector";
import { LiveSample, PasteSample } from "./live-sample";

vi.mock("@/lib/api-client", async () => ({
  ...(await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client")),
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/hooks", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks")>()),
  useSecrets: () => ({
    secrets: [
      {
        id: "vault-signing-key",
        name: "Webhook signing key",
        kind: "api_key",
        visibility: "org",
        owner_user_id: null,
      },
      {
        id: "vault-basic-key",
        name: "Webhook Basic credentials",
        kind: "webhook_credentials",
        visibility: "org",
        owner_user_id: null,
      },
    ],
    kinds: [
      { kind: "api_key", name: "API key", json_schema: {} },
      { kind: "webhook_credentials", name: "Webhook credentials", json_schema: {} },
    ],
    isLoading: false,
    create: { isPending: false, mutateAsync: vi.fn() },
  }),
}));
async function chooseSigningKey() {
  await userEvent.click(screen.getByRole("combobox", { name: "Secret" }));
  await userEvent.click(screen.getByRole("option", { name: /Webhook signing key/ }));
}
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
let subscribers: SourceUsage["items"] = [];
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
  subscribers = [];
  vi.mocked(apiClient.get).mockImplementation(async (path) => {
    if (path === "/me/permissions")
      return { permissions: permissions.map((permission) => ({ permission, scope: "all" })) };
    if (path === "/event-sources") return { items, total: items.length };
    if (path.endsWith("/usage")) return { items: subscribers, total: subscribers.length };
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

  it("loads recent deliveries only for the selected source, even without source-use permission", async () => {
    const user = userEvent.setup();
    permissions = ["event_sources:view"];
    items = [
      { ...source, can_use: false, can_edit: false },
      { ...source, id: "s2", name: "Other source", can_use: false, can_edit: false },
    ];
    const receipt: EventSourceDelivery = {
      id: "receipt-1",
      received_at: "2026-11-27T15:42:00Z",
      pending: 1,
      admitted: 2,
      skipped: 3,
      failed: 4,
    };
    const response = {
      items: [
        receipt,
        {
          id: "receipt-2",
          received_at: "2026-11-27T15:41:00Z",
          pending: 0,
          admitted: 0,
          skipped: 0,
          failed: 0,
        },
      ],
    };
    const get = vi.mocked(apiClient.get).getMockImplementation()!;
    let finish!: (result: typeof response) => void;
    const waiting = new Promise<typeof response>((resolve) => {
      finish = resolve;
    });
    const deliveries = vi
      .fn()
      .mockReturnValueOnce(waiting)
      .mockResolvedValueOnce({
        items: [{ ...receipt, pending: 0, admitted: 3 }],
      });
    vi.mocked(apiClient.get).mockImplementation(async (path, options) =>
      path.endsWith("/deliveries") ? deliveries(path) : get(path, options),
    );
    render(<SourceManager />, { wrapper });

    const trigger = await screen.findByRole("button", { name: "Recent deliveries for Issues" });
    expect(deliveries).not.toHaveBeenCalled();
    await user.click(trigger);
    const history = within(screen.getByRole("dialog", { name: "Recent deliveries for Issues" }));
    expect(history.getByRole("table")).toHaveAttribute("aria-busy", "true");
    expect(history.getByRole("button", { name: "Refresh" })).toBeDisabled();
    expect(deliveries).toHaveBeenCalledExactlyOnceWith("/event-sources/s1/deliveries");
    finish(response);

    const row = await history.findByRole("row", { name: /receipt-1/ });
    expect(row.querySelector("time")).toHaveAttribute("datetime", receipt.received_at);
    expect(history.queryByRole("button", { name: /Inspect delivery/ })).not.toBeInTheDocument();
    for (const label of ["1 pending", "2 handed off", "3 skipped", "4 failed"]) {
      expect(within(row).getByText(label)).toBeVisible();
    }
    expect(history.getByRole("row", { name: /receipt-2/ })).toHaveTextContent("No dispatches");
    await user.click(history.getByRole("button", { name: "Refresh" }));
    expect(await history.findByText("3 handed off")).toBeVisible();
    expect(history.queryByText("1 pending")).not.toBeInTheDocument();
  });

  it("distinguishes failed delivery history from no recent deliveries and can retry", async () => {
    const get = vi.mocked(apiClient.get).getMockImplementation()!;
    const deliveries = vi
      .fn()
      .mockRejectedValueOnce(new Error("History unavailable"))
      .mockResolvedValueOnce({ items: [] });
    vi.mocked(apiClient.get).mockImplementation(async (path, options) =>
      path.endsWith("/deliveries") ? deliveries() : get(path, options),
    );
    render(<SourceManager />, { wrapper });
    await userEvent.click(
      await screen.findByRole("button", { name: "Recent deliveries for Issues" }),
    );
    const history = within(screen.getByRole("dialog", { name: "Recent deliveries for Issues" }));
    expect(await history.findByRole("alert")).toHaveTextContent(
      "Recent deliveries could not be loaded.",
    );
    expect(history.queryByText("No recent deliveries.")).not.toBeInTheDocument();
    await userEvent.click(history.getByRole("button", { name: "Retry" }));
    expect(await history.findByText("No recent deliveries.")).toBeVisible();
    expect(history.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("lets source users drill into a receipt, refresh its details, and return to history", async () => {
    const user = userEvent.setup();
    items = [{ ...source, can_edit: false }];
    const receivedAt = "2026-11-27T15:42:00Z";
    const detail: EventSourceDeliveryDetail = {
      id: "receipt-1",
      received_at: receivedAt,
      external_id: "provider-delivery-1",
      request: {
        method: "POST",
        headers: { "x-github-event": "issues" },
        body: { action: "opened" },
      },
      response: { status_code: 202, headers: { "content-length": "0" }, body: null },
      dispatches: [
        {
          id: "dispatch-1",
          status: "failed",
          error_code: "SUBSCRIBER_UNAVAILABLE",
          completed_at: receivedAt,
        },
        { id: "dispatch-2", status: "pending", error_code: null, completed_at: null },
      ],
    };
    const inspect = vi
      .fn()
      .mockRejectedValueOnce(new Error("Details unavailable"))
      .mockResolvedValueOnce(detail)
      .mockResolvedValueOnce({
        ...detail,
        external_id: null,
        request: { ...detail.request, headers: {}, body: null },
        dispatches: [],
      });
    const get = vi.mocked(apiClient.get).getMockImplementation()!;
    vi.mocked(apiClient.get).mockImplementation(async (path, options) => {
      if (path === "/event-sources/s1/deliveries") {
        return {
          items: [
            {
              id: detail.id,
              received_at: receivedAt,
              pending: 1,
              admitted: 0,
              skipped: 0,
              failed: 1,
            },
          ],
        };
      }
      if (path === "/event-sources/s1/deliveries/receipt-1") return inspect(options);
      return get(path, options);
    });
    render(<SourceManager />, { wrapper });

    await user.click(await screen.findByRole("button", { name: "Recent deliveries for Issues" }));
    const action = await screen.findByRole("button", { name: "Inspect delivery receipt-1" });
    expect(inspect).not.toHaveBeenCalled();
    await user.click(action);
    const inspector = within(screen.getByRole("dialog", { name: "Delivery details" }));
    expect(await inspector.findByRole("alert")).toHaveTextContent(
      "Delivery details could not be loaded.",
    );
    expect(inspect).toHaveBeenCalledExactlyOnceWith({ signal: expect.any(AbortSignal) });

    const clipboard = Object.getOwnPropertyDescriptor(navigator, "clipboard");
    const execCommand = Object.getOwnPropertyDescriptor(document, "execCommand");
    const copy = vi
      .fn()
      .mockReturnValueOnce(false)
      .mockImplementationOnce(() => {
        const selected = document.activeElement;
        expect(selected).toBeInstanceOf(HTMLTextAreaElement);
        expect(selected).toHaveValue(JSON.stringify(detail.request.body, null, 2));
        return true;
      });
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: undefined });
    Object.defineProperty(document, "execCommand", { configurable: true, value: copy });
    try {
      await user.click(inspector.getByRole("button", { name: "Retry" }));
      expect(await inspector.findByText(/"action": "opened"/)).toBeVisible();
      expect(inspector.getByRole("heading", { name: "Request POST" })).toBeVisible();
      expect(inspector.getByRole("heading", { name: "Response HTTP 202" })).toBeVisible();
      expect(inspector.getByText("x-github-event")).toBeVisible();
      expect(inspector.getByText("content-length")).toBeVisible();
      expect(inspector.getByText("provider-delivery-1")).toBeVisible();
      expect(inspector.getByText("No response body.")).toBeVisible();
      expect(inspector.getByText("SUBSCRIBER_UNAVAILABLE")).toBeVisible();
      expect(inspector.getByText("Pending")).toBeVisible();

      await user.click(inspector.getByRole("button", { name: "Copy request body" }));
      expect(toast.error).toHaveBeenCalledWith("Copy failed");
      await user.click(inspector.getByRole("button", { name: "Copy request body" }));
      expect(inspector.getByRole("button", { name: "Copied to clipboard" })).toBeVisible();
      expect(copy).toHaveBeenCalledTimes(2);
      expect(copy).toHaveBeenLastCalledWith("copy");
    } finally {
      if (clipboard) Object.defineProperty(navigator, "clipboard", clipboard);
      else Reflect.deleteProperty(navigator, "clipboard");
      if (execCommand) Object.defineProperty(document, "execCommand", execCommand);
      else Reflect.deleteProperty(document, "execCommand");
    }

    await user.click(inspector.getByRole("button", { name: "Refresh" }));
    expect(await inspector.findByText("The request body is no longer retained.")).toBeVisible();
    expect(inspector.queryByRole("button", { name: "Copy request body" })).toBeNull();
    expect(inspector.getByText("No headers recorded.")).toBeVisible();
    expect(inspector.getByText("No dispatches")).toBeVisible();
    expect(inspector.queryByText("provider-delivery-1")).not.toBeInTheDocument();
    expect(inspect).toHaveBeenCalledTimes(3);

    await user.click(inspector.getByRole("button", { name: "Back to deliveries" }));
    const history = within(screen.getByRole("dialog", { name: "Recent deliveries for Issues" }));
    expect(
      await history.findByRole("button", { name: "Inspect delivery receipt-1" }),
    ).toBeVisible();
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

  it("links visible subscribers and leaves private subscribers as plain text", async () => {
    subscribers = [
      { id: "1", kind: "routine", target_id: null, name: null, is_active: null },
      { id: "2", kind: "workflow", target_id: null, name: null, is_active: null },
      { id: "3", kind: "routine", target_id: "r3", name: null, is_active: false },
      { id: "4", kind: "routine", target_id: "r4", name: "Private workflow", is_active: true },
      { id: "5", kind: "workflow", target_id: "w5", name: "Issue triage", is_active: true },
    ];
    render(<SourceManager />, { wrapper });
    await userEvent.click(await screen.findByRole("button", { name: "Subscribers" }));
    const dialog = within(screen.getByRole("dialog", { name: "Subscribers" }));
    expect((await dialog.findByText("Private routine")).closest("a")).toBeNull();
    expect(dialog.getByText("Private workflow").closest("a")).toBeNull();
    expect(dialog.getByRole("link", { name: "Routine · Paused" })).toHaveAttribute(
      "href",
      "/routines?routine=r3",
    );
    expect(
      dialog.getByRole("link", { name: "Private workflow · Routine · Active" }),
    ).toHaveAttribute("href", "/routines?routine=r4");
    expect(dialog.getByRole("link", { name: "Issue triage · Workflow · Active" })).toHaveAttribute(
      "href",
      "/workflows/w5",
    );
  });

  it("pauses only the source and explains the subscribers blocking deletion", async () => {
    subscribers = [
      { id: "sub1", kind: "routine", target_id: "r1", name: "Triage", is_active: true },
    ];
    render(<SourceManager />, { wrapper });
    await userEvent.click(await screen.findByRole("button", { name: "More actions for Issues" }));
    await waitFor(() =>
      expect(screen.getByRole("menuitem", { name: "Delete source" })).toHaveAttribute(
        "aria-disabled",
        "true",
      ),
    );
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
    await chooseSigningKey();
    const submit = dialog.getByRole("button", { name: "Replace credentials" });
    await user.click(submit);
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Credential replacement refused"));
    expect(screen.getByRole("combobox", { name: "Secret" })).toHaveTextContent(
      "Webhook signing key",
    );

    await user.click(submit);
    await waitFor(() => expect(screen.queryByLabelText("Secret")).not.toBeInTheDocument());
    expect(apiClient.post).toHaveBeenLastCalledWith("/event-sources/s1/credentials", {
      vault_secret_id: "vault-signing-key",
    });
  });

  it("deletes a source only after confirming and refreshes the catalog", async () => {
    const user = userEvent.setup();
    vi.mocked(apiClient.delete).mockImplementation(async () => {
      items = [];
    });
    render(<SourceManager />, { wrapper });

    await user.click(await screen.findByRole("button", { name: "More actions for Issues" }));
    await waitFor(() =>
      expect(screen.getByRole("menuitem", { name: "Delete source" })).not.toHaveAttribute(
        "aria-disabled",
        "true",
      ),
    );
    const deletion = screen.getByRole("menuitem", { name: "Delete source" });
    await user.click(deletion);
    expect(apiClient.delete).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Confirm deletion" }));
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Issues" })).toBeNull());
    expect(apiClient.delete).toHaveBeenCalledExactlyOnceWith("/event-sources/s1");
  });
  it("creates a private HMAC source using a Vault reference and handles a legacy creation receipt", async () => {
    render(<SourceSelector value={null} onChange={vi.fn()} />, { wrapper });
    await userEvent.click(await screen.findByRole("button", { name: "Create new source" }));
    expect(screen.getByRole("group", { name: "Create new source" })).toBeVisible();
    await userEvent.type(screen.getByLabelText("Name"), "Incoming");
    await chooseSigningKey();
    await userEvent.click(screen.getByRole("button", { name: "Create source" }));
    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith(
        "/event-sources",
        expect.objectContaining({
          name: "Incoming",
          provider: "webhook",
          visibility: "private",
          credentials: { vault_secret_id: "vault-signing-key" },
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
      await chooseSigningKey();
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
      const providerOption = screen.getByRole("option", { name: provider });
      expect(providerOption.querySelector("svg")).not.toBeNull();
      await userEvent.click(providerOption);
      expect(screen.queryByRole("combobox", { name: "Authentication" })).toBeNull();
      expect(screen.getByRole("button", { name: "Create source" })).toBeDisabled();
      await chooseSigningKey();
      await userEvent.click(screen.getByRole("button", { name: "Create source" }));
      expect(apiClient.post).toHaveBeenCalledWith(
        "/event-sources",
        expect.objectContaining({
          provider: provider.toLowerCase(),
          auth: { method: "provider" },
          credentials: { vault_secret_id: "vault-signing-key" },
        }),
      );
    },
  );
  it("submits only the Basic Auth Vault reference in the source creation request", async () => {
    render(<SourceForm onSaved={vi.fn()} onCancel={vi.fn()} />, { wrapper });
    await userEvent.type(screen.getByLabelText("Name"), "Basic");
    await userEvent.click(screen.getByRole("combobox", { name: "Authentication" }));
    await userEvent.click(screen.getByRole("option", { name: "Basic Auth" }));
    expect(screen.queryByLabelText("Username")).toBeNull();
    expect(screen.queryByLabelText("Password")).toBeNull();
    await userEvent.click(screen.getByRole("combobox", { name: "Secret" }));
    expect(screen.queryByRole("option", { name: /Webhook signing key/ })).toBeNull();
    await userEvent.click(screen.getByRole("option", { name: /Webhook Basic credentials/ }));
    await userEvent.click(screen.getByRole("button", { name: "Create source" }));
    expect(apiClient.post).toHaveBeenCalledWith(
      "/event-sources",
      expect.objectContaining({
        auth: { method: "basic" },
        credentials: { vault_secret_id: "vault-basic-key" },
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
    await chooseSigningKey();
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
});

it("offers source management beside the shared routine and workflow source picker", async () => {
  render(<SourceSelector value="s1" onChange={vi.fn()} />, { wrapper });
  expect(await screen.findByRole("link", { name: "Manage event sources" })).toHaveAttribute(
    "href",
    "/event-sources",
  );
});

it("does not offer source management without source visibility", async () => {
  permissions = [];
  render(<SourceSelector value={null} onChange={vi.fn()} />, { wrapper });
  await waitFor(() => expect(apiClient.get).toHaveBeenCalledWith("/me/permissions"));
  expect(screen.queryByRole("link", { name: "Manage event sources" })).toBeNull();
});

it("requires another compatible Vault selection after changing authentication method", async () => {
  render(<SourceForm onSaved={vi.fn()} onCancel={vi.fn()} />, { wrapper });
  await userEvent.type(screen.getByLabelText("Name"), "Events");
  await chooseSigningKey();
  expect(screen.getByRole("button", { name: "Create source" })).toBeEnabled();
  await userEvent.click(screen.getByRole("combobox", { name: "Authentication" }));
  await userEvent.click(screen.getByRole("option", { name: "Basic Auth" }));
  expect(screen.getByRole("button", { name: "Create source" })).toBeDisabled();
  expect(screen.getByRole("combobox", { name: "Secret" })).not.toHaveTextContent(
    "Webhook signing key",
  );
});

it("loads subscriber usage only for explicitly opened row details or actions", async () => {
  items = [source, { ...source, id: "s2", name: "Second source" }];
  render(<SourceManager />, { wrapper });
  await screen.findByRole("heading", { name: "Second source" });
  const usageRequests = () =>
    vi.mocked(apiClient.get).mock.calls.filter(([path]) => path.endsWith("/usage"));
  expect(usageRequests()).toHaveLength(0);
  const user = userEvent.setup();
  const [details] = screen.getAllByRole("button", { name: "Subscribers" });
  if (!details) throw new Error("Expected a subscriber details button");
  await user.click(details);
  await screen.findByText("No subscribers");
  expect(usageRequests().map(([path]) => path)).toEqual(["/event-sources/s1/usage"]);
  await user.keyboard("{Escape}");
  await user.click(screen.getByRole("button", { name: "More actions for Second source" }));
  await waitFor(() => expect(usageRequests()).toHaveLength(2));
  expect(usageRequests().map(([path]) => path)).toEqual([
    "/event-sources/s1/usage",
    "/event-sources/s2/usage",
  ]);
});

it.each(["Subscribers", "More actions for Issues"])(
  "reports usage failure after opening %s without enabling deletion",
  async (label) => {
    const get = vi.mocked(apiClient.get).getMockImplementation();
    vi.mocked(apiClient.get).mockImplementation(async (path, options) => {
      if (path.endsWith("/usage")) throw new Error("Usage unavailable");
      return get?.(path, options);
    });
    render(<SourceManager />, { wrapper });
    await userEvent.click(await screen.findByRole("button", { name: label }));
    expect(await screen.findByText("Subscribers could not be loaded.")).toBeVisible();
    if (label.startsWith("More")) {
      expect(screen.getByRole("menuitem", { name: "Delete source" })).toHaveAttribute(
        "aria-disabled",
        "true",
      );
    }
    expect(apiClient.delete).not.toHaveBeenCalled();
  },
);
