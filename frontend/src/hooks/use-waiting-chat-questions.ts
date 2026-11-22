"use client";

import { useInfiniteQuery } from "@tanstack/react-query";

import { listWaitingChatQuestions } from "@/lib/chat-questions-api";
import { qk } from "@/lib/query-keys";

export function useWaitingChatQuestions() {
  const query = useInfiniteQuery({
    queryKey: qk.conversations.waitingQuestions(),
    queryFn: ({ pageParam }) => listWaitingChatQuestions(pageParam),
    initialPageParam: 0,
    getNextPageParam: (last, _pages, offset) => {
      const next = offset + last.items.length;
      return last.items.length > 0 && next < last.total ? next : undefined;
    },
    refetchInterval: 30_000,
  });
  return {
    ...query,
    count: query.data?.pages[0]?.total ?? 0,
    items: query.data?.pages.flatMap((page) => page.items) ?? [],
  };
}
