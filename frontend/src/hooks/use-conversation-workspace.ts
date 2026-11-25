"use client";

import { skipToken, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";
import { useTranslations } from "next-intl";

import { getErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import {
  readConversationWorkspace,
  readConversationWorkspaceOrigins,
  workspaceOriginKey,
  type ConversationWorkspaceOrigin,
  type ConversationWorkspace,
} from "@/lib/conversation-workspace-api";
import { readWorkspaceFiles } from "@/lib/sandbox-workspaces-api";
import { listProjectFiles } from "@/lib/projects-api";
import type { FileSource } from "@/lib/workspace-files";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";

interface UseConversationWorkspaceResult {
  workspace: ConversationWorkspace | null;
  isLoading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  origins: ConversationWorkspaceOrigin[];
  selectedOrigin: ConversationWorkspaceOrigin | null;
  selectOrigin: (key: string) => void;
  originUnavailable: boolean;
  originsTruncated: boolean;
  source: FileSource | null;
  /** Identity and query prefix include the person, organization and exact origin. */
  contentKey: readonly unknown[];
}

/**
 * Legacy callers retain the conversation default. The Files panel opts into exact
 * origins: a removed location never redirects a selected path into another one.
 * Refresh is driven by terminal turns, not polling.
 */
export function useConversationWorkspace(
  conversationId: string | null,
  { originPicker = false }: { originPicker?: boolean } = {},
): UseConversationWorkspaceResult {
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();
  const ownerId = useAuthStore((state) => state.sessionOwnerId ?? state.user?.id ?? null);
  const orgId = useOrgStore((state) => state.activeOrgId);
  const contextKey = qk.conversationWorkspace.context(ownerId, orgId, conversationId);
  const context = JSON.stringify(contextKey);
  const [choice, setChoice] = useState<{ context: string; key: string | null } | null>(null);
  const originsQuery = useQuery({
    queryKey: [...contextKey, "origins"],
    queryFn:
      conversationId === null ? skipToken : () => readConversationWorkspaceOrigins(conversationId),
    enabled: originPicker && conversationId !== null && ownerId !== null,
    retry: false,
  });
  const origins = originsQuery.isError ? [] : (originsQuery.data?.items ?? []);
  const currentChoice = choice?.context === context ? choice : null;
  if (originPicker && originsQuery.isSuccess && currentChoice === null) {
    const initial = origins.find(
      (origin) =>
        origin.kind === originsQuery.data.default_origin &&
        origin.workspace_id === originsQuery.data.default_workspace_id,
    );
    setChoice({ context, key: initial ? workspaceOriginKey(initial) : null });
  }
  const selectedOrigin =
    origins.find((origin) => workspaceOriginKey(origin) === currentChoice?.key) ?? null;
  // Only a successful, initially empty inventory may use the old archive route.
  // A revoked origin or a failed inventory must never fall back to that default.
  const legacy =
    !originPicker ||
    (originsQuery.isSuccess &&
      origins.length === 0 &&
      originsQuery.data.default_origin === null &&
      currentChoice?.key === null);
  const source: Exclude<FileSource, { kind: "local" }> | null = legacy
    ? conversationId === null
      ? null
      : { kind: "conversation", id: conversationId }
    : selectedOrigin?.kind === "agent"
      ? { kind: "workspace", id: selectedOrigin.workspace_id }
      : selectedOrigin?.kind === "project" && selectedOrigin.project_id !== null
        ? { kind: "project", id: selectedOrigin.project_id }
        : null;
  const originKey = selectedOrigin ? workspaceOriginKey(selectedOrigin) : "legacy";
  const filesQuery = useQuery({
    queryKey: originPicker
      ? [...contextKey, "files", originKey]
      : qk.conversationWorkspace.files(conversationId ?? "none"),
    queryFn:
      source === null
        ? skipToken
        : async (): Promise<ConversationWorkspace> => {
            if (source.kind === "conversation") return readConversationWorkspace(source.id);
            const result =
              source.kind === "workspace"
                ? await readWorkspaceFiles(source.id)
                : await listProjectFiles(source.id);
            return {
              ...result,
              bytes_limit: null,
              items: result.items.map((file) => ({ ...file, preview: null, thumbnail: null })),
            };
          },
    enabled: source !== null && (!originPicker || ownerId !== null),
    retry: false,
  });
  const refresh = useCallback(async () => {
    if (conversationId === null) return;
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: qk.conversationWorkspace.files(conversationId) }),
      ...(originPicker
        ? [
            queryClient.invalidateQueries({
              queryKey: qk.conversationWorkspace.context(ownerId, orgId, conversationId),
            }),
          ]
        : []),
      queryClient.invalidateQueries({ queryKey: qk.codingChanges.all() }),
    ]);
  }, [queryClient, conversationId, originPicker, ownerId, orgId]);
  const error = (originPicker ? originsQuery.error : null) ?? filesQuery.error;
  const availableSource = error === null ? source : null;
  return {
    workspace: availableSource === null ? null : (filesQuery.data ?? null),
    isLoading:
      conversationId !== null && ((originPicker && originsQuery.isLoading) || filesQuery.isLoading),
    error: error ? getErrorMessage(error, tErrors) : null,
    refresh,
    origins,
    selectedOrigin,
    selectOrigin: (key) => {
      if (origins.some((origin) => workspaceOriginKey(origin) === key)) setChoice({ context, key });
    },
    originUnavailable:
      originPicker && originsQuery.isSuccess && !legacy && availableSource === null,
    originsTruncated: originsQuery.data?.truncated ?? false,
    source: availableSource,
    contentKey: [...contextKey, "content", originKey],
  };
}
