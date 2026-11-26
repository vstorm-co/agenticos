import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { BundlePreview, TransferOperation } from "@/lib/portability-api";
import {
  downloadResourceExport,
  downloadBundleTransfer,
  getBundleTransfer,
  startBundleExport,
  startBundleUpload,
  uploadBundleFile,
  applyBundleTransfer,
  importResourceBundle,
  listImportDestinations,
  previewResourceExport,
  previewResourceImport,
} from "@/lib/portability-api";
import { ExportAgentDialog } from "./export-dialog";
import { ImportAgentDialog } from "./import-dialog";

const presentation = vi.hoisted(() => ({ loaded: false }));
vi.mock("@/hooks/use-agents", async (original) => ({
  ...(await original<typeof import("@/hooks/use-agents")>()),
  useAgent: (id: string | null) => ({
    agent:
      id && presentation.loaded
        ? { id, slug: "stable-researcher", has_avatar: false, avatar_color: 2 }
        : undefined,
  }),
}));

vi.mock("@/lib/portability-api", () => ({
  downloadResourceExport: vi.fn(),
  downloadBundleTransfer: vi.fn(),
  startBundleExport: vi.fn(),
  startBundleUpload: vi.fn(),
  uploadBundleFile: vi.fn(),
  getBundleTransfer: vi.fn(),
  applyBundleTransfer: vi.fn(),
  importResourceBundle: vi.fn(),
  listImportDestinations: vi.fn(),
  previewResourceExport: vi.fn(),
  previewResourceImport: vi.fn(),
}));
const push = vi.fn();
vi.mock("@/hooks/use-console-router", () => ({ useConsoleRouter: () => ({ push }) }));

const preview: BundlePreview = {
  bundle: {
    format: "agenticos.bundle",
    format_version: 1,
    roots: ["agent/root"],
    assets: [],
    resources: [
      {
        key: "agent/root",
        kind: "agent",
        name: "Researcher",
        source_id: null,
        source_parent_id: null,
        source_version: null,
        definition: { name: "Researcher" },
        references: [],
        included: ["definition"],
      },
      {
        key: "context/policy",
        kind: "context",
        name: "Policy",
        source_id: "policy",
        source_parent_id: null,
        source_version: null,
        definition: { content: "Private policy" },
        references: [],
        included: ["definition"],
      },
      {
        key: "secret/key",
        kind: "secret",
        name: "Provider key",
        source_id: "key",
        source_parent_id: null,
        source_version: null,
        definition: null,
        references: [],
        included: [],
      },
    ],
  },
  options: [
    { key: "agent/root", available: true, can_create: true, reusable_id: null },
    { key: "context/policy", available: true, can_create: true, reusable_id: "destination-policy" },
    { key: "secret/key", available: false, can_create: false, reusable_id: null },
  ],
};

function Wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.clearAllMocks();
  presentation.loaded = false;
  vi.mocked(listImportDestinations).mockResolvedValue({
    items: [
      { id: "destination-policy", name: "Existing policy" },
      { id: "chosen-policy", name: "Chosen policy" },
    ],
    total: 2,
    searchable: true,
  });
  vi.mocked(previewResourceExport).mockResolvedValue(preview);
  vi.mocked(previewResourceImport).mockResolvedValue(preview);
  vi.mocked(downloadResourceExport).mockResolvedValue();
  vi.mocked(getBundleTransfer).mockResolvedValue(transferRow());
});

describe("agent portability", () => {
  it("downloads only the explicitly selected content and keeps keys as references", async () => {
    render(<ExportAgentDialog agentId="source" open onOpenChange={vi.fn()} />, {
      wrapper: Wrapper,
    });
    const policy = await screen.findByRole("checkbox", { name: /Policy/ });
    expect(screen.getByRole("checkbox", { name: /Researcher/ })).toBeDisabled();
    expect(screen.getByText("Provider key")).toBeVisible();
    expect(screen.getAllByRole("checkbox")).toHaveLength(2);
    await userEvent.click(policy);
    expect(policy).not.toBeChecked();
    await userEvent.click(policy);
    expect(policy).toBeChecked();
    await userEvent.click(policy);
    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.click(screen.getByRole("option", { name: "JSON" }));
    await userEvent.click(screen.getByRole("button", { name: "Download" }));
    await waitFor(() =>
      expect(downloadResourceExport).toHaveBeenCalledWith("agent", "source", "json", {
        "agent/root": ["definition"],
        "context/policy": [],
        "secret/key": [],
      }),
    );
  });

  it("keeps a failed export visible and allows retrying", async () => {
    vi.mocked(downloadResourceExport).mockRejectedValueOnce(new Error("Download failed"));
    const close = vi.fn();
    render(<ExportAgentDialog agentId="source" open onOpenChange={close} />, { wrapper: Wrapper });
    await screen.findByText("Policy");
    await userEvent.click(screen.getByRole("button", { name: "Download" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Download failed");
    await userEvent.click(screen.getByRole("button", { name: "Download" }));
    await waitFor(() => expect(downloadResourceExport).toHaveBeenCalledTimes(2));
    await userEvent.click(screen.getByText("Close", { selector: "button" }));
  });

  it("reviews mappings, renames only the new root, and retries with the same operation identity", async () => {
    vi.mocked(importResourceBundle).mockRejectedValueOnce(new Error("Connection lost"));
    vi.mocked(importResourceBundle).mockResolvedValueOnce({
      roots: { "agent/root": "new-agent" },
      created: { "agent/root": "new-agent" },
      reused: { "context/policy": "destination-policy" },
      skipped: ["secret/key"],
    });
    const close = vi.fn();
    render(<ImportAgentDialog open onOpenChange={close} />, { wrapper: Wrapper });
    fireEvent.change(screen.getByRole("textbox", { name: "Or paste the configuration" }), {
      target: { value: "name: Researcher" },
    });
    await userEvent.click(screen.getByRole("button", { name: "Review dependencies" }));
    await screen.findByRole("group", { name: "Researcher" });
    expect(screen.getByRole("combobox", { name: "Action for Researcher" })).toBeDisabled();
    const name = screen.getByRole("textbox", { name: "Name of the new copy" });
    fireEvent.change(name, { target: { value: "Researcher copy" } });
    expect(await screen.findByText("Existing policy")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Import private drafts" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Connection lost");
    await userEvent.click(screen.getByRole("button", { name: "Import private drafts" }));
    await screen.findByText("Import complete");
    const first = vi.mocked(importResourceBundle).mock.calls[0]?.[1];
    const second = vi.mocked(importResourceBundle).mock.calls[1]?.[1];
    expect(first?.operation_id).toBe(second?.operation_id);
    expect(first?.choices).toEqual({
      "agent/root": { action: "create", name: "Researcher copy" },
      "context/policy": { action: "reuse", destination_id: "destination-policy" },
      "secret/key": { action: "skip" },
    });
    await userEvent.click(screen.getByRole("button", { name: "Open draft" }));
    expect(push).toHaveBeenCalledWith("/agents/new-agent");
    expect(close).toHaveBeenCalledWith(false);
  });

  it("reads a file and keeps it editable when the preview is refused", async () => {
    vi.mocked(previewResourceImport).mockRejectedValueOnce(new Error("Invalid configuration"));
    render(<ImportAgentDialog open onOpenChange={vi.fn()} />, { wrapper: Wrapper });
    const file = new File(["name: From file"], "agent.yaml", { type: "application/yaml" });
    await userEvent.upload(
      screen.getByLabelText("Choose a ZIP, YAML or JSON file", { selector: "input" }),
      file,
    );
    await userEvent.click(screen.getByRole("button", { name: "Review dependencies" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid configuration");
    expect(screen.getByRole("textbox", { name: "Or paste the configuration" })).toHaveValue(
      "name: From file",
    );
    expect(vi.mocked(previewResourceImport).mock.calls[0]?.[1]).toBe("name: From file");
  });

  it("refuses an oversized or unreadable file before requesting a preview", async () => {
    render(<ImportAgentDialog open onOpenChange={vi.fn()} />, { wrapper: Wrapper });
    const input = screen.getByLabelText("Choose a ZIP, YAML or JSON file", { selector: "input" });
    const oversized = new File(["content"], "huge.json", { type: "application/json" });
    Object.defineProperty(oversized, "size", { value: 5 * 1024 * 1024 });
    await userEvent.upload(input, oversized);
    expect(await screen.findByRole("alert")).toHaveTextContent("4 MiB");
    const unreadable = new File(["{}"], "broken.json", { type: "application/json" });
    vi.spyOn(unreadable, "text").mockRejectedValueOnce(new Error("Read error"));
    await userEvent.upload(input, unreadable);
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be read");
    expect(previewResourceImport).not.toHaveBeenCalled();
  });

  it("keeps loading and failed export states explicit instead of offering an empty file", async () => {
    const request = Promise.withResolvers<BundlePreview>();
    vi.mocked(previewResourceExport).mockReturnValue(request.promise);
    const close = vi.fn();
    render(<ExportAgentDialog agentId="source" open onOpenChange={close} />, { wrapper: Wrapper });
    expect(screen.getByRole("status")).toHaveTextContent("Loading dependencies");
    expect(screen.getByRole("button", { name: "Download" })).toBeDisabled();
    request.reject(new Error("Dependencies unavailable"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Dependencies unavailable");
    await userEvent.click(screen.getByText("Close", { selector: "button" }));
    expect(close).toHaveBeenCalledWith(false);
    expect(downloadResourceExport).not.toHaveBeenCalled();
  });

  it("allows changing a mapping without modifying the uploaded definition", async () => {
    vi.mocked(importResourceBundle).mockResolvedValue({
      roots: { "agent/root": "copy" },
      created: {},
      reused: {},
      skipped: [],
    });
    render(<ImportAgentDialog open onOpenChange={vi.fn()} />, { wrapper: Wrapper });
    fireEvent.change(screen.getByRole("textbox", { name: "Or paste the configuration" }), {
      target: { value: "name: Researcher" },
    });
    await userEvent.click(screen.getByRole("button", { name: "Review dependencies" }));
    await screen.findByRole("group", { name: "Policy" });
    await userEvent.click(screen.getByRole("combobox", { name: "Action for Policy" }));
    await userEvent.click(screen.getByRole("option", { name: "Create a copy" }));
    expect(screen.getAllByRole("textbox", { name: "Name of the new copy" })).toHaveLength(2);
    await userEvent.click(screen.getByRole("combobox", { name: "Action for Policy" }));
    await userEvent.click(screen.getByRole("option", { name: "Skip this resource" }));
    expect(
      screen.queryByRole("combobox", { name: "Destination resource" }),
    ).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("combobox", { name: "Action for Policy" }));
    await userEvent.click(screen.getByRole("option", { name: "Use an existing resource" }));
    await userEvent.click(await screen.findByRole("combobox", { name: "Destination resource" }));
    await userEvent.click(await screen.findByRole("option", { name: "Chosen policy" }));
    await userEvent.click(screen.getByRole("button", { name: "Import private drafts" }));
    await screen.findByText("Import complete");
    expect(vi.mocked(importResourceBundle).mock.calls[0]?.[1].choices["context/policy"]).toEqual({
      action: "reuse",
      destination_id: "chosen-policy",
    });
    expect(preview.bundle.resources[1]?.definition).toEqual({ content: "Private policy" });
  });

  it("returns to the editable file and handles file-picker cancellation", async () => {
    const close = vi.fn();
    render(<ImportAgentDialog open onOpenChange={close} />, { wrapper: Wrapper });
    const input = screen.getByLabelText("Choose a ZIP, YAML or JSON file", { selector: "input" });
    const pick = vi.spyOn(input, "click");
    await userEvent.click(screen.getByRole("button", { name: "Choose a ZIP, YAML or JSON file" }));
    expect(pick).toHaveBeenCalledOnce();
    fireEvent.change(input, { target: { files: [] } });
    fireEvent.change(screen.getByRole("textbox", { name: "Or paste the configuration" }), {
      target: { value: "name: Researcher" },
    });
    await userEvent.click(screen.getByRole("button", { name: "Review dependencies" }));
    await screen.findByRole("group", { name: "Researcher" });
    await userEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByRole("textbox", { name: "Or paste the configuration" })).toHaveValue(
      "name: Researcher",
    );
    await userEvent.click(screen.getByText("Close", { selector: "button" }));
    expect(close).toHaveBeenCalledWith(false);
  });

  it("does not discard a pending review when Escape is pressed", async () => {
    const request = Promise.withResolvers<BundlePreview>();
    vi.mocked(previewResourceImport).mockReturnValue(request.promise);
    const close = vi.fn();
    render(<ImportAgentDialog open onOpenChange={close} />, { wrapper: Wrapper });
    fireEvent.change(screen.getByRole("textbox", { name: "Or paste the configuration" }), {
      target: { value: "name: Researcher" },
    });
    await userEvent.click(screen.getByRole("button", { name: "Review dependencies" }));
    await userEvent.keyboard("{Escape}");
    expect(close).not.toHaveBeenCalled();
    request.resolve(preview);
    await screen.findByRole("group", { name: "Researcher" });
  });
  it("keeps an incomplete receipt visible instead of navigating to an invented draft", async () => {
    vi.mocked(importResourceBundle).mockResolvedValue({
      roots: {},
      created: {},
      reused: {},
      skipped: [],
    });
    render(<ImportAgentDialog open onOpenChange={vi.fn()} />, { wrapper: Wrapper });
    fireEvent.change(screen.getByRole("textbox", { name: "Or paste the configuration" }), {
      target: { value: "name: Researcher" },
    });
    await userEvent.click(screen.getByRole("button", { name: "Review dependencies" }));
    await screen.findByRole("group", { name: "Researcher" });
    await userEvent.click(screen.getByRole("button", { name: "Import private drafts" }));
    await screen.findByText("Import complete");
    await userEvent.click(screen.getByRole("button", { name: "Open draft" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("did not identify the new draft");
    expect(push).not.toHaveBeenCalled();
  });
  it("selects export content from metadata without downloading linked bodies for the dialog", async () => {
    vi.mocked(previewResourceExport).mockResolvedValue({
      ...preview,
      bundle: {
        ...preview.bundle,
        resources: preview.bundle.resources.map((item) => ({
          ...item,
          definition: null,
          included: [],
          references: [],
        })),
      },
      options: preview.options.map((item) => ({
        ...item,
        layers: item.key === "secret/key" ? [] : ["definition"],
      })),
    });
    render(<ExportAgentDialog agentId="source" open onOpenChange={vi.fn()} />, {
      wrapper: Wrapper,
    });
    expect(await screen.findByRole("checkbox", { name: /Policy/ })).toBeChecked();
    await userEvent.click(screen.getByRole("button", { name: "Download" }));
    await waitFor(() =>
      expect(downloadResourceExport).toHaveBeenCalledWith("agent", "source", "yaml", {
        "agent/root": ["definition"],
        "context/policy": ["definition"],
        "secret/key": [],
      }),
    );
  });
  it("clears a version selection when its destination owner changes", async () => {
    const owner = {
      ...preview.bundle.resources[1]!,
      key: "skill/owner",
      kind: "skill",
      name: "Skill owner",
      source_id: "source-skill",
      definition: { name: "Skill owner" },
    };
    const version = {
      ...owner,
      key: "skill_version/pin",
      kind: "skill_version",
      name: "Pinned version",
      source_id: null,
      source_parent_id: "source-skill",
      source_version: "3",
    };
    vi.mocked(previewResourceImport).mockResolvedValue({
      bundle: { ...preview.bundle, resources: [preview.bundle.resources[0]!, owner, version] },
      options: [
        preview.options[0]!,
        { key: owner.key, available: true, can_create: true, reusable_id: "destination-policy" },
        { key: version.key, available: true, can_create: true, reusable_id: "old-version" },
      ],
    });
    vi.mocked(listImportDestinations).mockImplementation(async (query) =>
      query.kind === "skill_version"
        ? { items: [{ id: "new-version", name: "v3" }], total: 1, searchable: false }
        : {
            items: [
              { id: "destination-policy", name: "Original skill" },
              { id: "chosen-policy", name: "Other skill" },
            ],
            total: 2,
            searchable: true,
          },
    );
    render(<ImportAgentDialog open onOpenChange={vi.fn()} />, { wrapper: Wrapper });
    fireEvent.change(screen.getByRole("textbox", { name: "Or paste the configuration" }), {
      target: { value: "name: Agent" },
    });
    await userEvent.click(screen.getByRole("button", { name: "Review dependencies" }));
    const ownerRow = await screen.findByRole("group", { name: "Skill owner" });
    await waitFor(() =>
      expect(
        within(ownerRow).getByRole("combobox", { name: "Destination resource" }),
      ).toBeEnabled(),
    );
    await userEvent.click(within(ownerRow).getByRole("combobox", { name: "Destination resource" }));
    await userEvent.click(await screen.findByRole("option", { name: "Other skill" }));
    expect(screen.getByRole("button", { name: "Import private drafts" })).toBeDisabled();
    const versionRow = screen.getByRole("group", { name: "Pinned version" });
    await waitFor(() =>
      expect(
        within(versionRow).getByRole("combobox", { name: "Destination resource" }),
      ).toBeEnabled(),
    );
    await userEvent.click(
      within(versionRow).getByRole("combobox", { name: "Destination resource" }),
    );
    await userEvent.click(await screen.findByRole("option", { name: "v3" }));
    expect(screen.getByRole("button", { name: "Import private drafts" })).toBeEnabled();
    expect(listImportDestinations).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "skill_version", parent_id: "chosen-policy" }),
    );
  });
});

const transferRow = (patch: Partial<TransferOperation> = {}): TransferOperation => ({
  id: "transfer",
  request_id: "request",
  direction: "import",
  phase: "prepare",
  status: "review",
  revision: 1,
  completed_bytes: 20,
  total_bytes: 20,
  expires_at: "2026-11-26T12:00:00Z",
  error_code: null,
  preview,
  receipt: null,
  can_download: false,
  ...patch,
});

it("queues a ZIP export, then downloads the ready private transfer", async () => {
  vi.mocked(getBundleTransfer).mockResolvedValue(
    transferRow({ direction: "export", status: "ready", can_download: true }),
  );
  vi.mocked(startBundleExport).mockResolvedValue(
    transferRow({ direction: "export", status: "ready", can_download: true }),
  );
  vi.mocked(downloadBundleTransfer).mockResolvedValue();
  render(<ExportAgentDialog agentId="source" open onOpenChange={vi.fn()} />, { wrapper: Wrapper });
  await screen.findByText("Researcher");
  await userEvent.click(screen.getByRole("combobox", { name: "File format" }));
  await userEvent.click(screen.getByRole("option", { name: "ZIP · includes files" }));
  await userEvent.click(screen.getByRole("button", { name: /^Download$/ }));
  await waitFor(() => expect(startBundleExport).toHaveBeenCalled());
  await waitFor(() => expect(screen.getByRole("button", { name: /^Download$/ })).toBeEnabled());
  await userEvent.click(screen.getByRole("button", { name: /^Download$/ }));
  await waitFor(() =>
    expect(downloadBundleTransfer).toHaveBeenCalledWith("transfer", expect.anything()),
  );
  expect(downloadResourceExport).not.toHaveBeenCalled();
});

it("uploads ZIP bytes, reviews the manifest, and applies only the reviewed choices", async () => {
  vi.mocked(startBundleUpload).mockResolvedValue(
    transferRow({ status: "awaiting_upload", preview: null }),
  );
  vi.mocked(uploadBundleFile).mockResolvedValue(transferRow());
  const receipt = {
    roots: { "agent/root": "new-agent" },
    created: { "agent/root": "new-agent" },
    reused: {},
    skipped: [],
  };
  vi.mocked(applyBundleTransfer).mockResolvedValue(
    transferRow({ phase: "apply", status: "ready", revision: 2, receipt }),
  );
  render(<ImportAgentDialog open onOpenChange={vi.fn()} />, { wrapper: Wrapper });
  const file = new File(["zip bytes"], "researcher.zip", { type: "application/zip" });
  fireEvent.change(
    screen.getByLabelText("Choose a ZIP, YAML or JSON file", { selector: "input" }),
    { target: { files: [file] } },
  );
  await screen.findByText("researcher.zip");
  await userEvent.click(screen.getByRole("button", { name: "Review dependencies" }));
  await screen.findByRole("group", { name: "Policy" });
  expect(uploadBundleFile).toHaveBeenCalledWith("transfer", file);
  expect(previewResourceImport).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Import private drafts" }));
  await screen.findByText("Import complete");
  expect(vi.mocked(applyBundleTransfer).mock.calls[0]?.slice(0, 2)).toEqual(["transfer", 1]);
  expect(importResourceBundle).not.toHaveBeenCalled();
});

it("rejects an oversized ZIP before ticket creation", async () => {
  render(<ImportAgentDialog open onOpenChange={vi.fn()} />, { wrapper: Wrapper });
  const file = new File(["x"], "large.zip");
  Object.defineProperty(file, "size", { value: 512 * 1024 * 1024 + 1 });
  fireEvent.change(
    screen.getByLabelText("Choose a ZIP, YAML or JSON file", { selector: "input" }),
    { target: { files: [file] } },
  );
  expect(await screen.findByRole("alert")).toHaveTextContent("512 MiB");
  expect(startBundleUpload).not.toHaveBeenCalled();
});

it("closes export with Escape when no operation is running", async () => {
  const close = vi.fn();
  render(<ExportAgentDialog agentId="source" open onOpenChange={close} />, { wrapper: Wrapper });
  await screen.findByText("Researcher");
  await userEvent.keyboard("{Escape}");
  expect(close).toHaveBeenCalledWith(false);
});

it("expands export without losing reviewed choices and uses the source agent identity", async () => {
  presentation.loaded = true;
  const { container } = render(<ExportAgentDialog agentId="source" open onOpenChange={vi.fn()} />, {
    wrapper: Wrapper,
  });
  const policy = await screen.findByRole("checkbox", { name: /Policy/ });
  expect(container.ownerDocument.querySelector('[data-agent-avatar="source"]')).toBeInTheDocument();
  await userEvent.click(policy);
  await userEvent.click(screen.getByRole("button", { name: "Full screen" }));
  expect(screen.getByRole("checkbox", { name: /Policy/ })).not.toBeChecked();
  await userEvent.click(screen.getByRole("button", { name: "Exit full screen" }));
  await userEvent.click(screen.getByRole("button", { name: "Download" }));
  await waitFor(() =>
    expect(downloadResourceExport).toHaveBeenCalledWith("agent", "source", "yaml", {
      "agent/root": ["definition"],
      "context/policy": [],
      "secret/key": [],
    }),
  );
});
