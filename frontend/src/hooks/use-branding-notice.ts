/**
 * The announcement banner, for a signed-in user.
 *
 * Its own hook rather than part of the branding context: the context is resolved
 * once on the server and never changes for the life of a page, and an
 * announcement is the one field an operator writes expecting people already
 * looking at the product to see it. So this one polls, gently.
 *
 * Not read at all when nobody is signed in. The endpoint refuses that, and a
 * sign-in page asking for an operator's upgrade notes would be a 401 on every
 * cold load.
 */

import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api-client";
import type { NoticeResponse } from "@/lib/branding";
import { qk } from "@/lib/query-keys";

/** Long enough not to be traffic, short enough that a window announced at 21:55
 *  reaches somebody who has had the tab open since lunch. */
const POLL_INTERVAL_MS = 5 * 60 * 1000;

export function useBrandingNotice(enabled: boolean) {
  return useQuery({
    queryKey: qk.branding.notice(),
    queryFn: () => apiClient.get<NoticeResponse>("/branding/notice"),
    enabled,
    refetchInterval: POLL_INTERVAL_MS,
  });
}
