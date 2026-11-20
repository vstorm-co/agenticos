import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import type { BrowserTeaching } from "@/lib/browser-teaching-api";
import { useAuthStore, useOrgStore } from "@/stores";
import { useBrowserTeaching } from "./use-browser-teaching";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), patch: vi.fn(), post: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));
vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const TEACHING: BrowserTeaching = {
  id: "t1",
  agent_id: "a1",
  run_id: "r1",
  title: "Download invoice",
  allowed_origins: ["https://portal.example.test"],
  status: "review",
  revision: 4,
  reason_code: null,
  events: [
    {
      sequence: 1,
      action: "input_parameter",
      origin: "https://portal.example.test",
      target: { role: "textbox", fingerprint: "sha256:synthetic" },
      direction: null,
      human_step: false,
    },
  ],
  review: [],
  parameters: [],
  proposal_name: null,
  proposal_id: null,
  expires_at: "2026-11-18T09:00:00Z",
};

const STEP = { sequence: 1, label: "Invoice number", parameter: "invoice_number" };

beforeEach(() => {
  vi.clearAllMocks();
  useOrgStore.setState({ activeOrgId: "org-1" });
  useAuthStore.setState({ user: { id: "user-1" } as never });
  vi.mocked(apiClient.get).mockResolvedValue(TEACHING);
});

describe("reviewing a taught task", () => {
  it("reads the session and names the reader's identity", async () => {
    const { result } = renderHook(() => useBrowserTeaching("t1"), { wrapper });

    await waitFor(() => expect(result.current.teaching).toEqual(TEACHING));
    expect(apiClient.get).toHaveBeenCalledWith("/browser-teachings/t1");
    expect(result.current.identity).toBe("org-1:user-1");
  });

  it("saves a review against the revision it read", async () => {
    const saved = { ...TEACHING, revision: 5, review: [STEP], parameters: ["invoice_number"] };
    vi.mocked(apiClient.patch).mockResolvedValue(saved);
    const { result } = renderHook(() => useBrowserTeaching("t1"), { wrapper });
    await waitFor(() => expect(result.current.teaching).toBeDefined());

    let answer: BrowserTeaching | undefined;
    await act(async () => {
      answer = await result.current.saveReview([STEP]);
    });

    expect(answer).toEqual(saved);
    expect(apiClient.patch).toHaveBeenCalledWith(
      "/browser-teachings/t1",
      { action: "review", steps: [STEP] },
      { headers: { "If-Match": "4" } },
    );
    await waitFor(() => expect(result.current.teaching?.revision).toBe(5));
  });

  it("proposes from the session a save returned, not the stale one", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ ...TEACHING, status: "proposing", revision: 6 });
    const { result } = renderHook(() => useBrowserTeaching("t1"), { wrapper });
    await waitFor(() => expect(result.current.teaching).toBeDefined());

    await act(async () => {
      await result.current.propose("download-invoice", { ...TEACHING, revision: 5 });
    });

    expect(apiClient.post).toHaveBeenCalledWith(
      "/browser-teachings/t1/propose",
      { name: "download-invoice" },
      { headers: { "If-Match": "5" } },
    );
  });

  it("says so when a stale edit is refused and reads the session again", async () => {
    vi.mocked(apiClient.patch).mockRejectedValue(new Error("409"));
    const { result } = renderHook(() => useBrowserTeaching("t1"), { wrapper });
    await waitFor(() => expect(result.current.teaching).toBeDefined());

    let answer: BrowserTeaching | undefined = TEACHING;
    await act(async () => {
      answer = await result.current.saveReview([STEP]);
    });

    expect(answer).toBeUndefined();
    expect(toast.error).toHaveBeenCalled();
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(2));
  });

  it("reads afresh for another organization instead of showing the previous review", async () => {
    const { result, rerender } = renderHook(() => useBrowserTeaching("t1"), { wrapper });
    await waitFor(() => expect(result.current.teaching).toBeDefined());

    act(() => useOrgStore.setState({ activeOrgId: "org-2" }));
    rerender();

    expect(result.current.identity).toBe("org-2:user-1");
    expect(result.current.teaching).toBeUndefined();
  });

  it("writes nothing before the session has loaded", async () => {
    vi.mocked(apiClient.get).mockReturnValue(new Promise(() => undefined));
    const { result } = renderHook(() => useBrowserTeaching("t1"), { wrapper });

    await act(async () => {
      expect(await result.current.saveReview([STEP])).toBeUndefined();
      await result.current.propose("download-invoice");
    });

    expect(apiClient.patch).not.toHaveBeenCalled();
    expect(apiClient.post).not.toHaveBeenCalled();
  });
});
