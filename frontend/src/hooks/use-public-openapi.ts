"use client";

import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api-client";
import type { OpenApiDocument } from "@/lib/openapi/reference";
import { qk } from "@/lib/query-keys";

/** The public API's OpenAPI document: every route an organization key may call. */
export function usePublicOpenApi() {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.publicApi.openapi(),
    queryFn: () => apiClient.get<OpenApiDocument>("/public/openapi.json"),
    staleTime: Infinity,
  });
  return { document: data ?? null, isLoading, error, refetch };
}
