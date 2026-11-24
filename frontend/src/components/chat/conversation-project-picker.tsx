"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { ProjectPickerDialog } from "@/components/projects/project-picker-dialog";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";

export function ConversationProjectPicker({
  conversationId,
  projectId,
  open,
  onOpenChange,
}: {
  conversationId: string | null;
  projectId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("chat");
  const queryClient = useQueryClient();
  const move = useMutation({
    mutationFn: (nextProjectId: string | null) =>
      apiClient.patch(`/conversations/${conversationId}`, { project_id: nextProjectId }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: qk.conversations.all() }),
        queryClient.invalidateQueries({
          queryKey: qk.conversations.messages(conversationId ?? ""),
        }),
        queryClient.invalidateQueries({
          queryKey: qk.conversations.projectOf(conversationId ?? ""),
        }),
        queryClient.invalidateQueries({ queryKey: qk.projects.all() }),
      ]);
      onOpenChange(false);
      toast.success(t("projectMoved"));
    },
    onError: () => toast.error(t("projectMoveFailed")),
  });

  return (
    <ProjectPickerDialog
      open={open}
      onOpenChange={onOpenChange}
      selectedId={projectId}
      onPick={(project) => move.mutate(project?.id ?? null)}
    />
  );
}
