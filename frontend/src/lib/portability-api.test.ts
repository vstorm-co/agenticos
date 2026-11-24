import { beforeEach, expect, it, vi } from "vitest";
import { apiClient } from "./api-client";
import { saveBlob } from "./file-access";
import {
  downloadAgentExport,
  importAgentBundle,
  listImportDestinations,
  previewAgentExport,
  previewAgentImport,
} from "./portability-api";
import type { ResourceBundle } from "./portability-api";

vi.mock("./api-client", () => ({ apiClient: { get: vi.fn(), post: vi.fn(), raw: vi.fn() } }));
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
