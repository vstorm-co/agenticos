"use client";

import { useMutation } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { isWorkflowMediaScopeCurrent } from "./use-workflow-media-scope";
import { estimateWorkflowMedia } from "@/lib/workflows/media-api";
import type { WorkflowMediaEstimateRequest } from "@/lib/workflows/types";

/** The keyed form owns this calculation; changing config or identity aborts its old read. */
export function useWorkflowMediaEstimate(request: WorkflowMediaEstimateRequest, scope: string) {
  const active = useRef<AbortController | null>(null);
  useEffect(() => () => active.current?.abort(), []);
  return useMutation({
    mutationFn: async () => {
      active.current?.abort();
      const controller = new AbortController();
      active.current = controller;
      if (!isWorkflowMediaScopeCurrent(scope)) throw new Error();
      const estimate = await estimateWorkflowMedia(request, controller.signal);
      controller.signal.throwIfAborted();
      if (!isWorkflowMediaScopeCurrent(scope)) throw new Error();
      return estimate;
    },
    retry: false,
  });
}
