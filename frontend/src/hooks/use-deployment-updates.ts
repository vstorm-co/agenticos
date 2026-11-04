"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";

const operationSchema = z.object({
  id: z.string(),
  version: z.string(),
  phase: z.enum([
    "preparing",
    "ready",
    "scheduled",
    "draining",
    "backing_up",
    "applying",
    "checking",
    "succeeded",
    "failed",
    "cancelled",
  ]),
  created_at: z.number(),
  updated_at: z.number(),
  scheduled_for: z.number().nullable(),
  commit: z.string(),
  previous_commit: z.string(),
  reason: z.string().nullable(),
  backup_id: z.string().nullable(),
  images: z.record(z.string(), z.string()),
});
const statusSchema = z.object({
  configured: z.boolean(),
  reachable: z.boolean(),
  pipeline_url: z.string().nullable(),
  operation: operationSchema.nullable(),
});

export function useDeploymentUpdates() {
  const client = useQueryClient();
  const status = useQuery({
    queryKey: qk.admin.updates(),
    queryFn: async ({ signal }) =>
      statusSchema.parse(await apiClient.get<unknown>("/admin/updates", { signal })),
    refetchInterval: (query) =>
      query.state.data?.operation &&
      !["succeeded", "failed", "cancelled"].includes(query.state.data.operation.phase)
        ? 5000
        : 60_000,
    retry: false,
  });
  const action = useMutation({
    mutationFn: ({
      kind,
      payload,
    }: {
      kind: "prepare" | "apply" | "cancel";
      payload: { version: string } | { id: string; scheduled_for?: number | null };
    }) => apiClient.post<unknown>(`/admin/updates/${kind}`, payload),
    onSettled: () => client.invalidateQueries({ queryKey: qk.admin.updates() }),
  });
  return { status, action };
}
