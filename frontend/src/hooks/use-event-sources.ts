"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import {
  eventSourcesApi,
  type EventSourceCreate,
  type SourceCredentials,
} from "@/lib/event-sources-api";
import { getErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";

export function useEventSources(enabled = true) {
  return useQuery({ queryKey: qk.eventSources.list(), queryFn: eventSourcesApi.list, enabled });
}
export function useEventSource(id: string | null) {
  return useQuery({
    queryKey: qk.eventSources.detail(id ?? ""),
    queryFn: () => eventSourcesApi.get(id!),
    enabled: id !== null,
  });
}
export function useEventSourceUsage(id: string) {
  return useQuery({
    queryKey: qk.eventSources.usage(id),
    queryFn: () => eventSourcesApi.usage(id),
  });
}
export function useEventSourceWrites() {
  const cache = useQueryClient();
  const t = useTranslations("errors");
  const options = {
    onSuccess: () => cache.invalidateQueries({ queryKey: qk.eventSources.all() }),
    onError: (error: Error) => toast.error(getErrorMessage(error, t)),
  };
  return {
    create: useMutation({
      mutationFn: (input: EventSourceCreate) => eventSourcesApi.create(input),
      ...options,
    }),
    update: useMutation({
      mutationFn: ({
        id,
        input,
      }: {
        id: string;
        input: Parameters<typeof eventSourcesApi.update>[1];
      }) => eventSourcesApi.update(id, input),
      ...options,
    }),
    remove: useMutation({ mutationFn: eventSourcesApi.remove, ...options }),
    credentials: useMutation({
      mutationFn: ({ id, credentials }: { id: string; credentials: SourceCredentials }) =>
        eventSourcesApi.credentials(id, credentials),
      ...options,
    }),
  };
}
export function useSourceListener(id: string, token: string | null) {
  const listen = useMutation({ mutationFn: () => eventSourcesApi.listen(id) });
  const capture = useQuery({
    queryKey: qk.eventSources.capture(id, token ?? ""),
    queryFn: () => eventSourcesApi.capture(id, token!),
    enabled: token !== null,
    refetchInterval: (query) =>
      query.state.data?.state === "caught" ||
      query.state.data?.state === "expired" ||
      query.state.data?.state === "too_large" ||
      query.state.error
        ? false
        : 1500,
  });
  return { listen, capture };
}
export function usePromptPreview(agentId: string) {
  return useMutation({
    mutationFn: (input: Parameters<typeof eventSourcesApi.preview>[1]) =>
      eventSourcesApi.preview(agentId, input),
  });
}
