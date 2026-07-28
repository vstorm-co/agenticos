import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useSkill, useSkills } from "./use-skills";
import { apiClient } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
const toastSuccess = vi.fn();
vi.mock("sonner", () => ({
  toast: { success: (...args: unknown[]) => toastSuccess(...args), error: vi.fn() },
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useSkills", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
  });

  it("lists skills", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [{ id: "s1", name: "refunds", description: "How refunds work", enabled: true }],
      total: 1,
    });
    const { result } = renderHook(() => useSkills(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.skills[0]?.name).toBe("refunds");
  });

  it("asks the database for the slice, rather than filtering what it happens to hold", async () => {
    // An organization's skills grow without bound, so the client never has them
    // all — a client-side filter would search whichever fifty arrived first.
    const { result } = renderHook(() => useSkills({ search: "refund", skip: 50, limit: 50 }), {
      wrapper,
    });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(apiClient.get).toHaveBeenCalledWith("/skills", {
      params: { q: "refund", skip: "50", limit: "50" },
    });
  });

  it("reports the count before paging, which is what tells a caller it has a page", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 120 });
    const { result } = renderHook(() => useSkills(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.total).toBe(120);
  });

  it("creates a skill", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ name: "refunds" });
    const { result } = renderHook(() => useSkills(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await result.current.create.mutateAsync({
      name: "refunds",
      description: "How refunds work",
      content: "# Refunds",
    });
    expect(apiClient.post).toHaveBeenCalledWith(
      "/skills",
      expect.objectContaining({ name: "refunds" }),
    );
  });

  it("says an edit reaches every agent at once", async () => {
    // Skills are bound by reference. That is the whole point, and the person
    // editing one should know it before they hit save.
    vi.mocked(apiClient.patch).mockResolvedValue({ name: "refunds" });
    const { result } = renderHook(() => useSkills(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await result.current.update.mutateAsync({ id: "s1", content: "# Refunds v2" });

    expect(apiClient.patch).toHaveBeenCalledWith("/skills/s1", { content: "# Refunds v2" });
    expect(toastSuccess.mock.calls.at(-1)?.[0]).toMatch(/every agent/i);
  });

  it("deletes a skill", async () => {
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    const { result } = renderHook(() => useSkills(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await result.current.remove.mutateAsync("s1");
    expect(apiClient.delete).toHaveBeenCalledWith("/skills/s1");
  });
});

const BODY = {
  id: "s1",
  name: "refunds",
  description: "How refunds work",
  content: "# Refunds",
  enabled: true,
  version: 1,
  visibility: "organization",
  owner_user_id: null,
};

describe("useSkill", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.get).mockResolvedValue(BODY);
  });

  it("loads the body the list left out", async () => {
    const { result } = renderHook(() => useSkill("s1"), { wrapper });
    await waitFor(() => expect(result.current.skill).toEqual(BODY));
    expect(apiClient.get).toHaveBeenCalledWith("/skills/s1");
  });

  it("asks for nothing until a skill is opened", () => {
    // Bodies can be long; the list page must not fetch one per row.
    renderHook(() => useSkill(null), { wrapper });
    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("sends the whole editable set, so an unticked toggle is not lost", async () => {
    vi.mocked(apiClient.patch).mockResolvedValue(BODY);
    const { result } = renderHook(() => useSkill("s1"), { wrapper });
    await waitFor(() => expect(result.current.skill).toEqual(BODY));

    await result.current.save.mutateAsync({
      description: "How refunds work",
      content: "# Refunds v2",
      enabled: false,
    });

    expect(apiClient.patch).toHaveBeenCalledWith("/skills/s1", {
      description: "How refunds work",
      content: "# Refunds v2",
      enabled: false,
    });
    expect(toastSuccess.mock.calls.at(-1)?.[0]).toMatch(/every agent/i);
  });
});
