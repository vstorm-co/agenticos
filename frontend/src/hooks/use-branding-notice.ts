/**
 * What this deployment's state has become since the page was rendered.
 *
 * Its own hook rather than part of the branding context: the context is resolved
 * once on the server and never changes for the life of a page, and these are the
 * two fields an operator writes *expecting* people already looking at the product
 * to notice. So this one polls.
 *
 * Two answers from one request, deliberately. The announcement is what it was
 * written for; the maintenance verdict rides along because a page whose gate
 * cannot hear about a window is a page left on a dashboard answering 503 to
 * everything - and two endpoints on two intervals would be two answers about one
 * row that can disagree.
 *
 * Not read at all when nobody is signed in. The endpoint refuses that, and a
 * sign-in page asking for an operator's upgrade notes would be a 401 on every
 * cold load.
 */

import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api-client";
import type { NoticeResponse } from "@/lib/branding";
import { qk } from "@/lib/query-keys";

/**
 * How often an open page asks.
 *
 * A minute, which was five: an announcement can wait, but the maintenance verdict
 * decides whether the page in front of somebody is usable at all, and five minutes
 * of a dashboard failing every request is the defect this poll exists to close. It
 * is one indexed-by-nothing read of one row per signed-in tab.
 */
const POLL_INTERVAL_MS = 60 * 1000;

export function useBrandingNotice(enabled: boolean) {
  return useQuery({
    queryKey: qk.branding.notice(),
    queryFn: () => apiClient.get<NoticeResponse>("/branding/notice"),
    enabled,
    refetchInterval: POLL_INTERVAL_MS,
  });
}
