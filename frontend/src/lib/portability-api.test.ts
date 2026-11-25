import { beforeEach, expect, it, vi } from "vitest";
import { apiClient } from "./api-client";
import { saveBlob } from "./file-access";
import {
  downloadAgentExport,
  downloadBundleTransfer,
  startBundleExport,
  startBundleUpload,
  uploadBundleFile,
  getBundleTransfer,
  applyBundleTransfer,
  importAgentBundle,
  listImportDestinations,
  previewAgentExport,
  previewAgentImport,
} from "./portability-api";
import type { ResourceBundle } from "./portability-api";

vi.mock("./api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), put: vi.fn(), raw: vi.fn() },
}));
vi.mock("./file-access", () => ({ saveBlob: vi.fn() }));

beforeEach(() => vi.clearAllMocks());

it("uses the authenticated organization-aware API for previews and reviewed imports", async () => {
  const response = { reviewed: true };
  vi.mocked(apiClient.get).mockResolvedValue(response);
  vi.mocked(apiClient.post).mockResolvedValue(response);
  expect(await previewAgentExport("agent-1")).toBe(response);
  expect(apiClient.get).toHaveBeenCalledWith("/agents/agent-1/export-preview");
  expect(await previewAgentImport("name: Researcher")).toBe(response);
  expect(apiClient.post).toHaveBeenCalledWith("/agents/import-preview", {
    text: "name: Researcher",
  });
  const bundle: ResourceBundle = {
    format: "agenticos.bundle",
    format_version: 1,
    roots: ["agent/root"],
    resources: [],
    assets: [],
  };
  const request = {
    operation_id: "same-operation",
    bundle,
    choices: { "agent/root": { action: "create" as const } },
  };
  expect(await importAgentBundle(request)).toBe(response);
  expect(apiClient.post).toHaveBeenCalledWith("/agents/import", request);
});

it("downloads selected definitions through the API and saves the actual response bytes", async () => {
  vi.mocked(apiClient.raw).mockResolvedValue(
    new Response("name: Researcher", { headers: { "content-type": "application/yaml" } }),
  );
  await downloadAgentExport("agent-1", "yaml", { "agent/root": ["definition"] });
  expect(apiClient.raw).toHaveBeenCalledWith("/agents/agent-1/export", {
    method: "POST",
    body: { file_format: "yaml", resources: { "agent/root": ["definition"] } },
  });
  const blob = vi.mocked(saveBlob).mock.calls[0]?.[0];
  expect(await blob?.text()).toBe("name: Researcher");
  expect(vi.mocked(saveBlob).mock.calls[0]?.[1]).toBe("agent-agent-1.yaml");
});

it("does not save an empty success file when the API refuses the export", async () => {
  vi.mocked(apiClient.raw).mockRejectedValue(new Error("Export refused"));
  await expect(downloadAgentExport("agent-1", "json", {})).rejects.toThrow("Export refused");
  expect(saveBlob).not.toHaveBeenCalled();
});

it("requests paginated authorized destination names, including an explicit version owner", async () => {
  vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
  await listImportDestinations({ kind: "context", search: "Policy & rules", skip: 25, limit: 25 });
  expect(apiClient.get).toHaveBeenLastCalledWith(
    "/agents/import-destinations?kind=context&search=Policy+%26+rules&skip=25&limit=25",
  );
  await listImportDestinations({
    kind: "skill_version",
    parent_id: "owner-id",
    search: "",
    skip: 0,
    limit: 25,
  });
  expect(apiClient.get).toHaveBeenLastCalledWith(
    "/agents/import-destinations?kind=skill_version&search=&skip=0&limit=25&parent_id=owner-id",
  );
});

it("uses ticketed binary upload and server-side review without embedding the ZIP in JSON", async () => {
  const row = { id: "transfer" };
  vi.mocked(apiClient.get).mockResolvedValue(row);
  vi.mocked(apiClient.post).mockResolvedValue(row);
  vi.mocked(apiClient.put).mockResolvedValue(row);
  const file = new File(["bytes"], "agent.zip", { type: "application/zip" });
  expect(await startBundleUpload(file, "request")).toBe(row);
  expect(apiClient.post).toHaveBeenLastCalledWith("/portability/uploads", {
    request_id: "request",
    filename: "agent.zip",
    size_bytes: 5,
  });
  expect(await uploadBundleFile("transfer", file)).toBe(row);
  expect(apiClient.put).toHaveBeenCalledWith("/portability/transfer/upload", file);
  const signal = new AbortController().signal;
  expect(await getBundleTransfer("transfer", signal)).toBe(row);
  expect(apiClient.get).toHaveBeenLastCalledWith("/portability/transfer", { signal });
  expect(await applyBundleTransfer("transfer", 4, {})).toBe(row);
  expect(apiClient.post).toHaveBeenLastCalledWith("/portability/transfer/apply", {
    expected_revision: 4,
    choices: {},
  });
  expect(await startBundleExport("agent", { "agent/root": ["definition"] }, "request")).toBe(row);
  expect(apiClient.post).toHaveBeenLastCalledWith("/portability/exports", {
    request_id: "request",
    root_kind: "agent",
    root_id: "agent",
    resources: { "agent/root": ["definition"] },
  });
});

it("saves the ZIP download only after an authorized successful response", async () => {
  vi.mocked(apiClient.raw).mockResolvedValue(new Response("archive"));
  await downloadBundleTransfer("transfer");
  expect(apiClient.raw).toHaveBeenCalledWith("/portability/transfer/download", { method: "GET" });
  const [blob, name] = vi.mocked(saveBlob).mock.calls[0] ?? [];
  expect(await blob?.text()).toBe("archive");
  expect(name).toBe("agenticos-transfer.zip");
});
