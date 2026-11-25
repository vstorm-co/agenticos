import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { useAuthStore, useOrgStore } from "@/stores";
import type { BundlePreview, BundleResource, TransferOperation } from "@/lib/portability-api";
import * as api from "@/lib/portability-api";
import { ExportResourceDialog } from "./resource-export-dialog";
import { ImportResourceDialog } from "./resource-import-dialog";

vi.mock("@/lib/portability-api", () => ({
  previewResourceExport: vi.fn(),
  previewResourceImport: vi.fn(),
  importResourceBundle: vi.fn(),
  downloadResourceExport: vi.fn(),
  downloadBundleTransfer: vi.fn(),
  startBundleExport: vi.fn(),
  startBundleUpload: vi.fn(),
  uploadBundleFile: vi.fn(),
  getBundleTransfer: vi.fn(),
  applyBundleTransfer: vi.fn(),
  listImportDestinations: vi.fn(),
}));
const push = vi.fn();
vi.mock("@/hooks/use-console-router", () => ({ useConsoleRouter: () => ({ push }) }));
const resource = (
  key: string,
  kind: string,
  name: string,
  overrides: Partial<BundleResource> = {},
): BundleResource => ({
  key,
  kind,
  name,
  source_id: null,
  source_parent_id: null,
  source_version: null,
  definition: null,
  references: [],
  included: [],
  ...overrides,
});
const preview: BundlePreview = {
  bundle: {
    format: "agenticos.bundle",
    format_version: 1,
    roots: ["workflow/root"],
    assets: [],
    resources: [
      resource("workflow/root", "workflow", "Sales review", {
        definition: { name: "Sales review", omitted: [["graph", "bindings", 0]] },
        included: ["definition"],
        references: [
          {
            path: ["graph", "nodes", 0, "config", "agent", "agent_id"],
            target: "agent/specialist",
            is_key: false,
            destination_field: "id",
          },
          {
            path: ["graph", "nodes", 0, "config", "agent", "version_id"],
            target: "agent_version/source",
            is_key: false,
            destination_field: "id",
          },
          {
            path: ["graph", "nodes", 1, "config", "auth", "secret_id"],
            target: "secret/access",
            is_key: false,
            destination_field: "id",
          },
        ],
      }),
      resource("knowledge_base/policy", "knowledge_base", "Policy documents", {
        definition: {
          name: "Policy documents",
          documents: [{ filename: "Policy.pdf" }],
          private_chunks: "Never render these chunks",
        },
        included: ["definition"],
      }),
      resource("secret/access", "secret", "HTTP credential"),
      resource("agent/specialist", "agent", "Support specialist", {
        source_id: "source-specialist",
      }),
      resource("agent_version/source", "agent_version", "Support published version", {
        source_id: "source-version",
        source_parent_id: "source-specialist",
      }),
    ],
  },
  options: [
    {
      key: "workflow/root",
      available: true,
      can_create: true,
      reusable_id: null,
      layers: ["definition"],
    },
    {
      key: "knowledge_base/policy",
      available: true,
      can_create: true,
      reusable_id: null,
      layers: ["definition", "kb_documents", "kb_parsed_text"],
    },
    { key: "secret/access", available: false, can_create: false, reusable_id: null, layers: [] },
    {
      key: "agent/specialist",
      available: true,
      can_create: false,
      reusable_id: "destination-specialist",
      reusable_name: "Support specialist",
      layers: [],
    },
    {
      key: "agent_version/source",
      available: false,
      can_create: false,
      reusable_id: null,
      layers: [],
    },
  ],
};
function Wrapper({ children }: { children: ReactNode }) {
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
  vi.resetAllMocks();
  sessionStorage.clear();
  useAuthStore.setState({ user: null });
  useOrgStore.setState({ activeOrgId: null });
  vi.mocked(api.previewResourceExport).mockResolvedValue(preview);
  vi.mocked(api.previewResourceImport).mockResolvedValue(preview);
  vi.mocked(api.listImportDestinations).mockResolvedValue({
    items: [{ id: "destination-version", name: "v6" }],
    total: 1,
    searchable: false,
  });
});

it("selects ZIP document layers without exporting indexes, credentials or chunk text", async () => {
  const row: TransferOperation = {
    id: "aeac9081-9af3-4055-b738-1f4f7741af71",
    request_id: "request",
    direction: "export",
    phase: "prepare",
    status: "ready",
    revision: 1,
    completed_bytes: 0,
    total_bytes: 0,
    expires_at: "2026-11-26",
    error_code: null,
    preview: null,
    receipt: null,
    can_download: false,
  };
  vi.mocked(api.startBundleExport).mockResolvedValue(row);
  vi.mocked(api.getBundleTransfer).mockResolvedValue(row);
  render(
    <ExportResourceDialog
      resourceId="workflow-id"
      rootKind="workflow"
      open
      onOpenChange={vi.fn()}
    />,
    { wrapper: Wrapper },
  );
  await screen.findByText("Policy documents");
  expect(screen.getByRole("checkbox", { name: "Original documents" })).toBeDisabled();
  expect(screen.getByText(/Search indexes and vectors are not included/)).toBeVisible();
  expect(screen.queryByText("Never render these chunks")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("combobox", { name: "File format" }));
  await userEvent.click(await screen.findByRole("option", { name: "ZIP · includes files" }));
  await userEvent.click(screen.getByRole("checkbox", { name: "Original documents" }));
  await userEvent.click(screen.getByRole("checkbox", { name: "Parsed text snapshots" }));
  await userEvent.click(screen.getByRole("button", { name: "Download" }));
  await waitFor(() =>
    expect(api.startBundleExport).toHaveBeenCalledWith(
      "workflow-id",
      expect.objectContaining({
        "knowledge_base/policy": ["definition", "kb_documents", "kb_parsed_text"],
        "secret/access": [],
      }),
      expect.any(String),
      "workflow",
    ),
  );
  expect(api.downloadResourceExport).not.toHaveBeenCalled();
  await waitFor(() => expect(screen.getByRole("combobox", { name: "File format" })).toBeEnabled());
  await userEvent.click(screen.getByRole("combobox", { name: "File format" }));
  await userEvent.click(await screen.findByRole("option", { name: "YAML" }));
  await userEvent.click(screen.getByRole("button", { name: "Download" }));
  await waitFor(() =>
    expect(api.downloadResourceExport).toHaveBeenCalledWith(
      "workflow",
      "workflow-id",
      "yaml",
      expect.objectContaining({ "knowledge_base/policy": ["definition"] }),
    ),
  );
});

it("reviews omitted bindings and manually maps a delegate's published version to its existing owner", async () => {
  vi.mocked(api.importResourceBundle).mockResolvedValue({
    roots: { "workflow/root": "new-workflow" },
    created: { "workflow/root": "new-workflow" },
    reused: {},
    skipped: ["secret/access"],
    omitted_bindings: { "workflow/root": [["graph", "bindings", 0]] },
  });
  render(<ImportResourceDialog rootKind="workflow" open onOpenChange={vi.fn()} />, {
    wrapper: Wrapper,
  });
  fireEvent.change(screen.getByRole("textbox", { name: "Or paste the configuration" }), {
    target: { value: "workflow bundle" },
  });
  await userEvent.click(screen.getByRole("button", { name: "Review dependencies" }));
  const group = await screen.findByRole("group", { name: "Support published version" });
  expect(screen.getByText("Bindings to remove: 3.")).toBeVisible();
  await userEvent.click(
    within(group).getByRole("combobox", { name: "Action for Support published version" }),
  );
  await userEvent.click(await screen.findByRole("option", { name: "Use an existing resource" }));
  await waitFor(() =>
    expect(api.listImportDestinations).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "agent_version", parent_id: "destination-specialist" }),
    ),
  );
  await userEvent.click(within(group).getByRole("combobox", { name: "Destination resource" }));
  await userEvent.click(await screen.findByRole("option", { name: "v6" }));
  expect(screen.getByText("Bindings to remove: 2.")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Import private drafts" }));
  await screen.findByText("Import complete");
  expect(api.importResourceBundle).toHaveBeenCalledWith(
    "workflow",
    expect.objectContaining({
      choices: expect.objectContaining({
        "agent_version/source": { action: "reuse", destination_id: "destination-version" },
      }),
    }),
  );
  expect(screen.getByText("Bindings removed: 1.")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Open draft" }));
  expect(push).toHaveBeenCalledWith("/workflows/new-workflow");
});

it("keeps older workflow import explicitly available without posting a bundle", async () => {
  const legacy = vi.fn();
  render(
    <ImportResourceDialog rootKind="workflow" open onOpenChange={vi.fn()} onLegacy={legacy} />,
    { wrapper: Wrapper },
  );
  await userEvent.click(screen.getByRole("button", { name: "Import an older workflow file" }));
  expect(legacy).toHaveBeenCalledOnce();
  expect(api.previewResourceImport).not.toHaveBeenCalled();
});

it("switches an interrupted ZIP upload to a fresh inline import without applying the old ticket", async () => {
  const { transferSessionKey, writeTransferSession } = await import("@/lib/transfer-session");
  const id = "aeac9081-9af3-4055-b738-1f4f7741af71";
  useAuthStore.setState({
    user: { id: "owner", email: "owner@example.com", is_active: true, created_at: "2026-01-01" },
  });
  useOrgStore.setState({ activeOrgId: "org" });
  writeTransferSession(transferSessionKey("org", "owner", "import:workflow"), id);
  vi.mocked(api.getBundleTransfer).mockResolvedValue({
    id,
    request_id: "request",
    direction: "import",
    phase: "prepare",
    status: "awaiting_upload",
    revision: 1,
    completed_bytes: 0,
    total_bytes: 5,
    expires_at: "2026-11-26",
    error_code: null,
    preview: null,
    receipt: null,
    can_download: false,
  });
  vi.mocked(api.importResourceBundle).mockResolvedValue({
    roots: { "workflow/root": "new" },
    created: {},
    reused: {},
    skipped: [],
  });
  render(<ImportResourceDialog rootKind="workflow" open onOpenChange={vi.fn()} />, {
    wrapper: Wrapper,
  });
  await screen.findByText(/The upload was interrupted/);
  fireEvent.change(screen.getByRole("textbox", { name: "Or paste the configuration" }), {
    target: { value: "inline workflow" },
  });
  await userEvent.click(screen.getByRole("button", { name: "Review dependencies" }));
  await screen.findByRole("group", { name: "Sales review" });
  await userEvent.click(screen.getByRole("button", { name: "Import private drafts" }));
  await screen.findByText("Import complete");
  expect(api.importResourceBundle).toHaveBeenCalledWith("workflow", expect.anything());
  expect(api.applyBundleTransfer).not.toHaveBeenCalled();
  expect(
    sessionStorage.getItem(transferSessionKey("org", "owner", "import:workflow") ?? ""),
  ).toBeNull();
});

it("refuses to apply a reviewed ZIP after access is revoked and resets its stale ticket", async () => {
  const { act } = await import("@testing-library/react");
  const { qk } = await import("@/lib/query-keys");
  const { transferSessionKey, writeTransferSession } = await import("@/lib/transfer-session");
  const id = "aeac9081-9af3-4055-b738-1f4f7741af71";
  useAuthStore.setState({
    user: { id: "owner", email: "owner@example.com", is_active: true, created_at: "2026-01-01" },
  });
  useOrgStore.setState({ activeOrgId: "org" });
  writeTransferSession(transferSessionKey("org", "owner", "import:workflow"), id);
  vi.mocked(api.getBundleTransfer)
    .mockResolvedValueOnce({
      id,
      request_id: "request",
      direction: "import",
      phase: "prepare",
      status: "review",
      revision: 1,
      completed_bytes: 5,
      total_bytes: 5,
      expires_at: "2026-11-26",
      error_code: null,
      preview,
      receipt: null,
      can_download: false,
    })
    .mockRejectedValue(new Error("Access revoked"));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  render(<ImportResourceDialog rootKind="workflow" open onOpenChange={vi.fn()} />, { wrapper });
  await screen.findByRole("group", { name: "Sales review" });
  await act(() => client.refetchQueries({ queryKey: qk.portability.transfer("org", "owner", id) }));
  await screen.findByRole("button", { name: "Start a new transfer" });
  await userEvent.click(screen.getByRole("button", { name: "Import private drafts" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("No reviewed transfer selected");
  expect(api.applyBundleTransfer).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Start a new transfer" }));
  expect(screen.getByRole("button", { name: "Choose a ZIP, YAML or JSON file" })).toBeVisible();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(
    sessionStorage.getItem(transferSessionKey("org", "owner", "import:workflow") ?? ""),
  ).toBeNull();
});

it.each([true, false])(
  "restores a completed import only from its authorized response (preview: %s)",
  async (withPreview) => {
    const { transferSessionKey, writeTransferSession } = await import("@/lib/transfer-session");
    const id = "aeac9081-9af3-4055-b738-1f4f7741af71";
    useAuthStore.setState({
      user: { id: "owner", email: "owner@example.com", is_active: true, created_at: "2026-01-01" },
    });
    useOrgStore.setState({ activeOrgId: "org" });
    writeTransferSession(transferSessionKey("org", "owner", "import:workflow"), id);
    vi.mocked(api.getBundleTransfer).mockResolvedValue({
      id,
      request_id: "request",
      direction: "import",
      phase: "apply",
      status: "ready",
      revision: 2,
      completed_bytes: 5,
      total_bytes: 5,
      expires_at: "2026-11-26",
      error_code: null,
      preview: withPreview ? preview : null,
      receipt: {
        roots: { "workflow/root": "restored-workflow" },
        created: { "workflow/root": "restored-workflow" },
        reused: {},
        skipped: [],
        omitted_bindings: { "workflow/root": [["graph", "bindings", 0]] },
      },
      can_download: false,
    });
    render(<ImportResourceDialog rootKind="workflow" open onOpenChange={vi.fn()} />, {
      wrapper: Wrapper,
    });
    await screen.findByText("Import complete");
    expect(screen.getByText("Bindings removed: 1.")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Open draft" }));
    expect(push).toHaveBeenCalledWith("/workflows/restored-workflow");
    expect(api.applyBundleTransfer).not.toHaveBeenCalled();
    expect(api.importResourceBundle).not.toHaveBeenCalled();
  },
);

it("keeps a running export open and offers an explicit fresh start after failure", async () => {
  const response = Promise.withResolvers<void>();
  vi.mocked(api.downloadResourceExport).mockReturnValue(response.promise);
  const close = vi.fn();
  const { unmount } = render(
    <ExportResourceDialog resourceId="workflow-id" rootKind="workflow" open onOpenChange={close} />,
    { wrapper: Wrapper },
  );
  await screen.findByText("Sales review");
  await userEvent.click(screen.getByRole("button", { name: "Download" }));
  await userEvent.keyboard("{Escape}");
  expect(close).not.toHaveBeenCalled();
  response.resolve();
  await waitFor(() => expect(screen.getByRole("button", { name: "Download" })).toBeEnabled());
  unmount();
  const { transferSessionKey, writeTransferSession } = await import("@/lib/transfer-session");
  const id = "aeac9081-9af3-4055-b738-1f4f7741af71";
  useAuthStore.setState({
    user: { id: "owner", email: "owner@example.com", is_active: true, created_at: "2026-01-01" },
  });
  useOrgStore.setState({ activeOrgId: "org" });
  writeTransferSession(transferSessionKey("org", "owner", "export:workflow:workflow-id"), id);
  vi.mocked(api.getBundleTransfer).mockResolvedValue({
    id,
    request_id: "request",
    direction: "export",
    phase: "prepare",
    status: "failed",
    revision: 1,
    completed_bytes: 0,
    total_bytes: 5,
    expires_at: "2026-11-26",
    error_code: "transfer_failed",
    preview: null,
    receipt: null,
    can_download: false,
  });
  render(
    <ExportResourceDialog
      resourceId="workflow-id"
      rootKind="workflow"
      open
      onOpenChange={vi.fn()}
    />,
    { wrapper: Wrapper },
  );
  expect(await screen.findByRole("alert")).toHaveTextContent("The transfer failed");
  await userEvent.click(screen.getByRole("button", { name: "Start a new transfer" }));
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(
    sessionStorage.getItem(transferSessionKey("org", "owner", "export:workflow:workflow-id") ?? ""),
  ).toBeNull();
});
