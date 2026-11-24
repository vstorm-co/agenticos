import { apiClient } from "@/lib/api-client";
import type { WorkflowMediaEstimateRead, WorkflowMediaEstimateRequest } from "./types";

/** Calculates the current catalog reservation; this route never calls a media provider. */
export function estimateWorkflowMedia(request: WorkflowMediaEstimateRequest, signal?: AbortSignal) {
  return apiClient.post<WorkflowMediaEstimateRead>("/workflows/media-estimate", request, {
    signal,
    cache: "no-store",
  });
}
