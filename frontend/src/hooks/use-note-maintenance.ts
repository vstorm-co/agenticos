"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { getErrorMessage } from "@/lib/api-error";
import {
  getNoteRevisions,
  restoreNoteRevision,
  setNoteAutoUpdate,
  type MemoryNote,
} from "@/lib/memory-api";
import { qk } from "@/lib/query-keys";
import { useOrgStore } from "@/stores";

export function useNoteMaintenance(note: MemoryNote, open: boolean, skip: number) {
  const org = useOrgStore((state) => state.activeOrgId) ?? "current";
  const queryClient = useQueryClient();
  const t = useTranslations("errors");
  const revisions = useQuery({
    queryKey: qk.memory.noteRevisions(org, note.id, skip),
    queryFn: () => getNoteRevisions(note.id, skip),
    enabled: open,
  });
  const invalidate = () => queryClient.invalidateQueries({ queryKey: qk.memory.all(org) });
  const toggle = useMutation({
    mutationFn: (enabled: boolean) => setNoteAutoUpdate(note, enabled),
    onSuccess: invalidate,
    onError: (error) => toast.error(getErrorMessage(error, t)),
  });
  const restore = useMutation({
    mutationFn: (id: string) => restoreNoteRevision(note, id),
    onSuccess: invalidate,
    onError: (error) => toast.error(getErrorMessage(error, t)),
  });
  return { revisions, toggle, restore };
}
