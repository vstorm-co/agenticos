import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  isIdentifyingContent,
  useAddKnowledgeGapContent,
  useAddKnowledgeGapToDataset,
  useDraftKnowledgeGap,
  useKnowledgeGap,
  useKnowledgeGaps,
  useClassifyKnowledgeGaps,
  useRegroupKnowledgeGaps,
  useSaveKnowledgeGapContent,
  useSetKnowledgeGapStatus,
} from "./use-knowledge-gaps";
import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), put: vi.fn() },
}));
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

beforeEach(() => {
  vi.clearAllMocks();
});

describe("useKnowledgeGaps", () => {
  it("lists every knowledge base the caller reads, open topics first page by default", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [{ id: "t1", label: "parental leave" }],
      total: 7,
      ungrouped: 3,
      can_regroup: true,
      unchecked: 8,
    });
    const { result } = renderHook(() => useKnowledgeGaps({ kind: "organization" }), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith("/knowledge-gaps?status=open&skip=0&limit=50");
    expect(result.current.topics[0]?.label).toBe("parental leave");
    expect(result.current.total).toBe(7);
    expect(result.current.ungrouped).toBe(3);
    expect(result.current.canRegroup).toBe(true);
    expect(result.current.unchecked).toBe(8);
  });

  it("asks one knowledge base, or one agent, for the status and page given", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0, ungrouped: 0 });
    renderHook(
      () => useKnowledgeGaps({ kind: "collection", id: "kb1" }, { status: "dismissed", skip: 50 }),
      { wrapper },
    );
    renderHook(() => useKnowledgeGaps({ kind: "agent", id: "a1" }, { limit: 5 }), { wrapper });
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(2));
    expect(apiClient.get).toHaveBeenCalledWith(
      "/knowledge-gaps/collections/kb1?status=dismissed&skip=50&limit=50",
    );
    expect(apiClient.get).toHaveBeenCalledWith(
      "/knowledge-gaps/agents/a1?status=open&skip=0&limit=5",
    );
  });

  it("reads an empty answer as nothing rather than throwing", async () => {
    vi.mocked(apiClient.get).mockResolvedValue(undefined);
    const { result } = renderHook(() => useKnowledgeGaps({ kind: "organization" }), { wrapper });
    await waitFor(() => expect(apiClient.get).toHaveBeenCalled());
    expect(result.current.topics).toEqual([]);
    expect(result.current.total).toBe(0);
    expect(result.current.ungrouped).toBe(0);
    expect(result.current.canRegroup).toBe(false);
    expect(result.current.unchecked).toBe(0);
  });
});

describe("useKnowledgeGap", () => {
  it("reads one topic with its questions", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ id: "t1", questions: [] });
    const { result } = renderHook(() => useKnowledgeGap("t1"), { wrapper });
    await waitFor(() => expect(result.current.topic?.id).toBe("t1"));
    expect(apiClient.get).toHaveBeenCalledWith("/knowledge-gaps/t1");
  });
});

describe("the topic mutations", () => {
  it("dismisses a topic and reopens it, saying which", async () => {
    const { result } = renderHook(() => useSetKnowledgeGapStatus(), { wrapper });
    vi.mocked(apiClient.post).mockResolvedValueOnce({ id: "t1", status: "dismissed" });
    await result.current.mutateAsync({ topicId: "t1", status: "dismissed" });
    expect(apiClient.post).toHaveBeenCalledWith("/knowledge-gaps/t1/dismiss");
    expect(toastSuccess).toHaveBeenCalledWith("Topic dismissed");

    vi.mocked(apiClient.post).mockResolvedValueOnce({ id: "t1", status: "open" });
    await result.current.mutateAsync({ topicId: "t1", status: "open" });
    expect(apiClient.post).toHaveBeenCalledWith("/knowledge-gaps/t1/reopen");
    expect(toastSuccess).toHaveBeenCalledWith("Topic reopened");
  });

  it("says why when the server refuses a status change", async () => {
    vi.mocked(apiClient.post).mockRejectedValueOnce(new Error("nope"));
    const { result } = renderHook(() => useSetKnowledgeGapStatus(), { wrapper });
    await expect(
      result.current.mutateAsync({ topicId: "t1", status: "dismissed" }),
    ).rejects.toThrow();
    await waitFor(() => expect(toastError).toHaveBeenCalled());
  });

  it("adds a topic's questions to a dataset and counts what was added and skipped", async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce({
      dataset_id: "d1",
      version: 4,
      added: 3,
      skipped: 1,
    });
    const { result } = renderHook(() => useAddKnowledgeGapToDataset(), { wrapper });
    await result.current.mutateAsync({ topicId: "t1", datasetId: "d1", name: "refunds" });
    expect(apiClient.post).toHaveBeenCalledWith("/knowledge-gaps/t1/dataset", {
      dataset_id: "d1",
    });
    expect(toastSuccess).toHaveBeenCalledWith("3 cases added to refunds, 1 question skipped");

    vi.mocked(apiClient.post).mockRejectedValueOnce(new Error("nope"));
    await expect(
      result.current.mutateAsync({ topicId: "t1", datasetId: "d1", name: "refunds" }),
    ).rejects.toThrow();
    await waitFor(() => expect(toastError).toHaveBeenCalled());
  });

  it("groups a knowledge base's waiting questions now", async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce(undefined);
    const { result } = renderHook(() => useRegroupKnowledgeGaps("kb1"), { wrapper });
    await result.current.mutateAsync();
    expect(apiClient.post).toHaveBeenCalledWith("/knowledge-gaps/collections/kb1/regroup");
    expect(toastSuccess).toHaveBeenCalledWith(
      "Grouping started. New topics appear in a minute or two.",
    );

    vi.mocked(apiClient.post).mockRejectedValueOnce(new Error("nope"));
    await expect(result.current.mutateAsync()).rejects.toThrow();
    await waitFor(() => expect(toastError).toHaveBeenCalled());
  });
});

describe("useClassifyKnowledgeGaps", () => {
  it("starts a check of a knowledge base's answers, and shows a refusal as the server says it", async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce(undefined);
    const { result } = renderHook(() => useClassifyKnowledgeGaps("kb1"), { wrapper });
    await result.current.mutateAsync();
    expect(apiClient.post).toHaveBeenCalledWith("/knowledge-gaps/collections/kb1/classify");
    expect(toastSuccess).toHaveBeenCalledWith(
      "Checking answers. New topics appear when it finishes. Its runs are in Activity, with evals included.",
    );

    vi.mocked(apiClient.post).mockRejectedValueOnce(new Error("AI assistance is off"));
    await expect(result.current.mutateAsync()).rejects.toThrow();
    await waitFor(() => expect(toastError).toHaveBeenCalled());
  });
});

describe("useDraftKnowledgeGap", () => {
  it("asks for a draft and says when it is ready", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ id: "t1", draft: { title: "x" } });
    const { result } = renderHook(() => useDraftKnowledgeGap(), { wrapper });
    result.current.mutate("t1");
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiClient.post).toHaveBeenCalledWith("/knowledge-gaps/t1/draft");
    expect(toastSuccess).toHaveBeenCalledWith("Draft ready - check it before you add it");
  });

  it("shows the server's refusal, such as AI assistance being off", async () => {
    vi.mocked(apiClient.post).mockRejectedValue(new Error("AI assistance is off"));
    const { result } = renderHook(() => useDraftKnowledgeGap(), { wrapper });
    result.current.mutate("t1");
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(toastError).toHaveBeenCalled();
  });
});

function identifying(): ApiError {
  return new ApiError(409, "This content may identify somebody.", {
    error: {
      code: "IDENTIFYING_CONTENT",
      message: "This content may identify somebody.",
      details: { flags: [{ kind: "shared", value: "7781", count: 1 }] },
    },
  });
}

describe("a topic's content", () => {
  it("saves what a person wrote without adding it anywhere", async () => {
    vi.mocked(apiClient.put).mockResolvedValue({ id: "t1" });
    const { result } = renderHook(() => useSaveKnowledgeGapContent(), { wrapper });
    result.current.mutate({ topicId: "t1", title: "Parking", content: "Level -1." });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiClient.put).toHaveBeenCalledWith("/knowledge-gaps/t1/draft", {
      title: "Parking",
      content: "Level -1.",
    });
    expect(toastSuccess).toHaveBeenCalledWith("Content saved");
  });

  it("says why when saving is refused", async () => {
    vi.mocked(apiClient.put).mockRejectedValue(new Error("Topic not found"));
    const { result } = renderHook(() => useSaveKnowledgeGapContent(), { wrapper });
    result.current.mutate({ topicId: "t1", title: "Parking", content: "Level -1." });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(toastError).toHaveBeenCalled();
  });

  it("adds it to the knowledge base, confirmed or not, and names where it went", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({
      id: "t1",
      knowledge_base_id: "kb1",
      knowledge_base_name: "Handbook",
    });
    const { result } = renderHook(() => useAddKnowledgeGapContent(), { wrapper });
    result.current.mutate({
      topicId: "t1",
      title: "Parking",
      content: "Level -1.",
      confirmed: [{ kind: "shared", value: "7781", count: 1 }],
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiClient.post).toHaveBeenCalledWith("/knowledge-gaps/t1/document", {
      title: "Parking",
      content: "Level -1.",
      confirmed: [{ kind: "shared", value: "7781", count: 1 }],
    });
    expect(toastSuccess).toHaveBeenCalledWith(
      "Added to Handbook. The document is being processed.",
    );
  });

  it("leaves content that may identify somebody to the editor, and toasts any other refusal", async () => {
    vi.mocked(apiClient.post).mockRejectedValueOnce(identifying());
    const { result } = renderHook(() => useAddKnowledgeGapContent(), { wrapper });
    const content = { topicId: "t1", title: "Parking", content: "x", confirmed: [] };
    result.current.mutate(content);
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(isIdentifyingContent(result.current.error)).toBe(true);
    expect(toastError).not.toHaveBeenCalled();

    vi.mocked(apiClient.post).mockRejectedValueOnce(new Error("Fill in what is still to fill in"));
    result.current.mutate(content);
    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(isIdentifyingContent(new Error("x"))).toBe(false);
  });
});
