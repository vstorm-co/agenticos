import type { QueryClient } from "@tanstack/react-query";
import { waitFor } from "@testing-library/react";
import { expect } from "vitest";

import { stoppedPolling } from "@/lib/live-polling";

/**
 * The one query a test mounted, once its first read is in: whether it polls, then
 * what it does after reading it again fails - the caller has arranged for every
 * request after the first to fail.
 */
export async function pollingAfterFailedRead(client: QueryClient) {
  await waitFor(() => expect(client.getQueryCache().getAll()[0]?.state.status).toBe("success"));
  const [query] = client.getQueryCache().getAll();
  if (query === undefined) throw new Error("no query mounted");
  const { refetchInterval } = query.options as {
    refetchInterval: (current: typeof query) => number | false;
  };
  const before = refetchInterval(query);
  await query.fetch().catch(() => undefined);
  return { before, after: refetchInterval(query), stopped: stoppedPolling(query) };
}
