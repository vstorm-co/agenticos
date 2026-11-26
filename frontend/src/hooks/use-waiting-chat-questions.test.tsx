import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { useWaitingChatQuestions } from "./use-waiting-chat-questions";

const get = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api-client", () => ({ apiClient: { get } }));

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return renderHook(useWaitingChatQuestions, {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  });
}

it("counts every waiting run and loads later pages from the personal endpoint", async () => {
  get
    .mockResolvedValueOnce({ total: 3, items: [{ run_id: "one" }, { run_id: "two" }] })
    .mockResolvedValueOnce({ total: 3, items: [{ run_id: "three" }] });
  const { result } = setup();
  expect(result.current.items).toEqual([]);
  await waitFor(() => expect(result.current.count).toBe(3));
  expect(result.current.items.map((item) => item.run_id)).toEqual(["one", "two"]);
  expect(result.current.hasNextPage).toBe(true);
  await act(async () => void (await result.current.fetchNextPage()));
  await waitFor(() => expect(result.current.items).toHaveLength(3));
  expect(result.current.hasNextPage).toBe(false);
  expect(get).toHaveBeenNthCalledWith(1, "/conversations/waiting-questions", {
    params: { skip: "0" },
  });
  expect(get).toHaveBeenNthCalledWith(2, "/conversations/waiting-questions", {
    params: { skip: "2" },
  });
});

it("does not repeatedly request the same page if the queue drains while loading", async () => {
  get.mockResolvedValueOnce({ total: 2, items: [] });
  const { result } = setup();
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(result.current.hasNextPage).toBe(false);
});
