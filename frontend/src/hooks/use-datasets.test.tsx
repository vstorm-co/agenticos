import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  exportDataset,
  useAddToDataset,
  useDataset,
  useDatasetCase,
  useDatasetCases,
  useDatasets,
  useDatasetVersions,
  useDatasetSource,
} from "./use-datasets";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import { saveBlob } from "@/lib/file-access";

vi.mock("@/lib/api-client", () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
    upload: vi.fn(),
    raw: vi.fn(),
  },
}));
vi.mock("@/lib/file-access", () => ({ saveBlob: vi.fn() }));
const toastSuccess = vi.fn();
const toastError = vi.fn();
vi.mock("sonner", () => ({
  toast: {
    success: (...args: unknown[]) => toastSuccess(...args),
    error: (...args: unknown[]) => toastError(...args),
  },
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const CONTENT = {
  input: "How long is the return window?",
  history: [],
  reference_answer: null,
  counter_example: null,
  expected_tool_calls: [],
  order_mode: "any" as const,
  checks: [],
  tags: [],
  note: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0, version: 0 });
});

describe("useDatasets", () => {
  it("asks the database for one slice and reports the count before paging", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [{ id: "d1", name: "refunds" }],
      total: 40,
    });
    const { result } = renderHook(
      () => useDatasets({ search: "ref", sort: "updated", skip: 20, limit: 20 }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith("/datasets?q=ref&sort=updated&skip=20&limit=20");
    expect(result.current.datasets[0]?.name).toBe("refunds");
    expect(result.current.total).toBe(40);
  });

  it("narrows to the datasets one judge grades", async () => {
    renderHook(() => useDatasets({ judge: "j1", limit: 3 }), { wrapper });
    await waitFor(() => expect(apiClient.get).toHaveBeenCalled());
    expect(apiClient.get).toHaveBeenCalledWith("/datasets?judge=j1&sort=name&skip=0&limit=3");
  });

  it("narrows to the datasets with a case asking one run's question, by the run's id", async () => {
    renderHook(() => useDatasets({ asksRun: "run-1", limit: 2 }), { wrapper });
    await waitFor(() => expect(apiClient.get).toHaveBeenCalled());
    expect(apiClient.get).toHaveBeenCalledWith("/datasets?asks_run=run-1&sort=name&skip=0&limit=2");
  });

  it("narrows to the datasets the caller may edit", async () => {
    renderHook(() => useDatasets({ editable: true, limit: 1 }), { wrapper });
    await waitFor(() => expect(apiClient.get).toHaveBeenCalled());
    expect(apiClient.get).toHaveBeenCalledWith("/datasets?editable=true&sort=name&skip=0&limit=1");
  });

  it("leaves the search out when there is none, and reads an empty answer as nothing", async () => {
    vi.mocked(apiClient.get).mockResolvedValue(undefined);
    const { result } = renderHook(() => useDatasets(), { wrapper });
    await waitFor(() => expect(apiClient.get).toHaveBeenCalled());
    expect(apiClient.get).toHaveBeenCalledWith("/datasets?sort=name&skip=0&limit=50");
    expect(result.current.datasets).toEqual([]);
    expect(result.current.total).toBe(0);
  });

  it("creates a dataset and says so by name", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ id: "d1", name: "refunds" });
    const { result } = renderHook(() => useDatasets(), { wrapper });
    await result.current.create.mutateAsync({ name: "refunds", description: null });
    expect(apiClient.post).toHaveBeenCalledWith("/datasets", {
      name: "refunds",
      description: null,
    });
    expect(toastSuccess).toHaveBeenCalledWith("Created refunds");
  });

  it("deletes one, and says why when the server refuses", async () => {
    const { result } = renderHook(() => useDatasets(), { wrapper });
    vi.mocked(apiClient.delete).mockResolvedValueOnce(undefined);
    await result.current.remove.mutateAsync("d1");
    expect(apiClient.delete).toHaveBeenCalledWith("/datasets/d1");
    expect(toastSuccess).toHaveBeenCalledWith("Dataset deleted");

    vi.mocked(apiClient.delete).mockRejectedValueOnce(new Error("nope"));
    await expect(result.current.remove.mutateAsync("d1")).rejects.toThrow();
    await waitFor(() => expect(toastError).toHaveBeenCalled());
  });
});

describe("useDataset and its versions", () => {
  it("reads one dataset and renames it without a new version", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ id: "d1", name: "refunds" });
    vi.mocked(apiClient.patch).mockResolvedValue({ id: "d1", name: "returns" });
    const { result } = renderHook(() => useDataset("d1"), { wrapper });
    await waitFor(() => expect(result.current.dataset?.name).toBe("refunds"));
    await result.current.update.mutateAsync({ name: "returns" });
    expect(apiClient.patch).toHaveBeenCalledWith("/datasets/d1", { name: "returns" });
  });

  it("deletes the dataset it reads, and says why when the server refuses", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ id: "d1", name: "refunds" });
    const { result } = renderHook(() => useDataset("d1"), { wrapper });
    await waitFor(() => expect(result.current.dataset?.name).toBe("refunds"));
    vi.mocked(apiClient.delete).mockResolvedValueOnce(undefined);
    await result.current.remove.mutateAsync();
    expect(apiClient.delete).toHaveBeenCalledWith("/datasets/d1");
    expect(toastSuccess).toHaveBeenCalledWith("Dataset deleted");

    vi.mocked(apiClient.delete).mockRejectedValueOnce(new Error("nope"));
    await expect(result.current.remove.mutateAsync()).rejects.toThrow();
    await waitFor(() => expect(toastError).toHaveBeenCalled());
  });

  it("reads one case for a link, and asks nothing without an id", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ case_id: "c1", input: "q" });
    const { result } = renderHook(() => useDatasetCase("d1", "c1"), { wrapper });
    await waitFor(() => expect(result.current.kase?.input).toBe("q"));
    expect(apiClient.get).toHaveBeenCalledWith("/datasets/d1/cases/c1");

    vi.mocked(apiClient.get).mockClear();
    const idle = renderHook(() => useDatasetCase("d1", null), { wrapper });
    expect(idle.result.current.isLoading).toBe(false);
    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("lists the versions newest first, as the server ordered them", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [{ number: 2 }, { number: 1 }], total: 2 });
    const { result } = renderHook(() => useDatasetVersions("d1"), { wrapper });
    await waitFor(() => expect(result.current.versions).toHaveLength(2));
    expect(apiClient.get).toHaveBeenCalledWith("/datasets/d1/versions?limit=100");
  });

  it("reads no versions as none", async () => {
    vi.mocked(apiClient.get).mockResolvedValue(undefined);
    const { result } = renderHook(() => useDatasetVersions("d1"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.versions).toEqual([]);
  });
});

describe("useDatasetCases", () => {
  it("asks for nothing until a dataset is chosen", () => {
    const { result } = renderHook(() => useDatasetCases(""), { wrapper });

    expect(apiClient.get).not.toHaveBeenCalled();
    expect(result.current.cases).toEqual([]);
  });

  it("reads the newest version unless one is named", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [{ id: "r1" }], total: 1, version: 3 });
    const { result } = renderHook(() => useDatasetCases("d1"), { wrapper });
    await waitFor(() => expect(result.current.version).toBe(3));
    expect(apiClient.get).toHaveBeenCalledWith("/datasets/d1/cases?skip=0&limit=50");

    renderHook(() => useDatasetCases("d1", { version: 2, skip: 20, limit: 20 }), { wrapper });
    await waitFor(() =>
      expect(apiClient.get).toHaveBeenCalledWith("/datasets/d1/cases?skip=20&limit=20&version=2"),
    );
  });

  it("finds the case already asking a question, or none, with the question kept out of the URL", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0, version: 1 });
    vi.mocked(apiClient.post).mockResolvedValue({ items: [], total: 0, version: 1 });
    const { result } = renderHook(() => useDatasetCases("d1"), { wrapper });

    expect(await result.current.findTwin("Return window?")).toBeNull();
    expect(apiClient.post).toHaveBeenLastCalledWith("/datasets/d1/cases/twins?limit=1", {
      input: "Return window?",
    });
    vi.mocked(apiClient.post).mockResolvedValue({ items: [{ id: "r1" }], total: 1, version: 1 });
    expect(await result.current.findTwin("Return window?")).toEqual({ id: "r1" });
    // However long: a body has no length a proxy refuses.
    expect(await result.current.findTwin("q".repeat(2_001))).toEqual({ id: "r1" });
    expect(apiClient.get).not.toHaveBeenCalledWith(expect.stringContaining("Return"));
  });

  it("reads an empty answer as no cases at version 0", async () => {
    vi.mocked(apiClient.get).mockResolvedValue(undefined);
    const { result } = renderHook(() => useDatasetCases("d1"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.cases).toEqual([]);
    expect(result.current.total).toBe(0);
    expect(result.current.version).toBe(0);
  });

  it("adds, edits and removes a case, each saying it made a new version", async () => {
    const { result } = renderHook(() => useDatasetCases("d1"), { wrapper });
    vi.mocked(apiClient.post).mockResolvedValue({});
    vi.mocked(apiClient.patch).mockResolvedValue({});
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);

    await result.current.add.mutateAsync(CONTENT);
    await result.current.update.mutateAsync({ caseId: "c1", content: CONTENT });
    await result.current.remove.mutateAsync("c1");

    expect(apiClient.post).toHaveBeenCalledWith("/datasets/d1/cases", CONTENT);
    expect(apiClient.patch).toHaveBeenCalledWith("/datasets/d1/cases/c1", CONTENT);
    expect(apiClient.delete).toHaveBeenCalledWith("/datasets/d1/cases/c1");
    expect(toastSuccess.mock.calls.map(([message]) => message)).toEqual([
      "Case added",
      "Case saved",
      "Case removed",
    ]);
  });

  it("names the version a change made, once the dataset has been read again", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(qk.datasets.detail("d1"), { id: "d1", latest_version: 4 });
    vi.mocked(apiClient.post).mockResolvedValue({});
    const { result } = renderHook(() => useDatasetCases("d1"), {
      wrapper: ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      ),
    });

    await result.current.add.mutateAsync(CONTENT);

    expect(toastSuccess).toHaveBeenLastCalledWith("Added as v4");
  });

  it("says when a removal is refused", async () => {
    vi.mocked(apiClient.delete).mockRejectedValue(new Error("gone"));
    const { result } = renderHook(() => useDatasetCases("d1"), { wrapper });
    await expect(result.current.remove.mutateAsync("c1")).rejects.toThrow();
    await waitFor(() => expect(toastError).toHaveBeenCalled());
  });

  it("imports a file as one version and says how many cases it held", async () => {
    vi.mocked(apiClient.upload).mockResolvedValue({ number: 4, changed_cases: 100 });
    const { result } = renderHook(() => useDatasetCases("d1"), { wrapper });
    const file = new File(["input\nq\n"], "cases.csv");
    await result.current.importFile.mutateAsync(file);
    expect(apiClient.upload).toHaveBeenCalledWith("/datasets/d1/import", file);
    expect(toastSuccess).toHaveBeenCalledWith("100 cases imported as version 4");
  });
});

describe("exportDataset", () => {
  it("saves the file under the name the server gave it", async () => {
    const blob = new Blob(["input\n"]);
    vi.mocked(apiClient.raw).mockResolvedValue({
      headers: new Headers({ "content-disposition": 'attachment; filename="dataset_v2.csv"' }),
      blob: () => Promise.resolve(blob),
    } as unknown as Response);
    await exportDataset("d1", { format: "csv", version: 2 });
    expect(apiClient.raw).toHaveBeenCalledWith("/datasets/d1/export", {
      params: { format: "csv", version: "2" },
    });
    expect(saveBlob).toHaveBeenCalledWith(blob, "dataset_v2.csv");
  });

  it("names the file itself when the server does not, and exports the newest by default", async () => {
    vi.mocked(apiClient.raw).mockResolvedValue({
      headers: new Headers(),
      blob: () => Promise.resolve(new Blob()),
    } as unknown as Response);
    await exportDataset("d1", { format: "jsonl", version: null });
    expect(apiClient.raw).toHaveBeenCalledWith("/datasets/d1/export", {
      params: { format: "jsonl" },
    });
    expect(vi.mocked(saveBlob).mock.calls[0]?.[1]).toBe("dataset.jsonl");
  });
});

describe("useAddToDataset", () => {
  it("sends the answer and what it is kept as", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({});
    const { result } = renderHook(() => useAddToDataset(), { wrapper });
    await result.current.mutateAsync({
      datasetId: "d1",
      messageId: "m1",
      answerAs: "counter_example",
      withHistory: true,
    });
    expect(apiClient.post).toHaveBeenCalledWith("/datasets/d1/cases/from-message", {
      message_id: "m1",
      answer_as: "counter_example",
      with_history: true,
    });

    await result.current.mutateAsync({
      datasetId: "d1",
      messageId: "m1",
      answerAs: "reference_answer",
      withHistory: false,
    });
    expect(apiClient.post).toHaveBeenLastCalledWith("/datasets/d1/cases/from-message", {
      message_id: "m1",
      answer_as: "reference_answer",
      with_history: false,
    });
  });
});

it("checks whether a source answer is private before copying it", async () => {
  vi.mocked(apiClient.get).mockResolvedValue({ private_to_other: true, owner_name: "Ada" });
  const { result } = renderHook(() => useDatasetSource("message-1", true), { wrapper });
  await waitFor(() =>
    expect(result.current.data).toEqual({ private_to_other: true, owner_name: "Ada" }),
  );
  expect(apiClient.get).toHaveBeenCalledWith("/datasets/messages/message-1/source");
});
