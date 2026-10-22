"use client";

import { useState } from "react";
import { EyeOff, FlaskConical, MoreHorizontal, RotateCcw } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui";
import { useSetKnowledgeGapStatus } from "@/hooks/use-knowledge-gaps";
import { usePermissions } from "@/hooks/use-permissions";
import { Perm } from "@/types/permissions";
import type { KnowledgeGapTopic } from "@/types/knowledge-gaps";
import { GapToDatasetDialog } from "./gap-to-dataset-dialog";

/**
 * A topic's rarer actions, behind "…": dismissing or reopening it - a covered
 * one too, which leaves its document in place - and turning its questions into
 * dataset cases.
 *
 * Dismissing follows the topic's own `can_edit` - an edit grant on its knowledge
 * base reaches it as the role does. Adding to a dataset is offered to anybody
 * who reads datasets, because the dialog offers only those they may change.
 * Absent when neither applies.
 */
export function KnowledgeGapActions({ topic }: { topic: KnowledgeGapTopic }) {
  const t = useTranslations("knowledgeGaps");
  const { can } = usePermissions();
  const setStatus = useSetKnowledgeGapStatus();
  const [addingToDataset, setAddingToDataset] = useState(false);
  const mayAddCases = can(Perm.datasetsView);
  if (!topic.can_edit && !mayAddCases) return null;

  const dismissed = topic.status !== "open";
  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon" className="size-8" aria-label={t("moreActions")}>
            <MoreHorizontal className="h-4 w-4" aria-hidden />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {topic.can_edit && (
            <DropdownMenuItem
              disabled={setStatus.isPending}
              onSelect={() =>
                setStatus.mutate({ topicId: topic.id, status: dismissed ? "open" : "dismissed" })
              }
            >
              {dismissed ? (
                <RotateCcw className="h-4 w-4" aria-hidden />
              ) : (
                <EyeOff className="h-4 w-4" aria-hidden />
              )}
              {dismissed ? t("reopen") : t("dismiss")}
            </DropdownMenuItem>
          )}
          {mayAddCases && (
            <DropdownMenuItem onSelect={() => setAddingToDataset(true)}>
              <FlaskConical className="h-4 w-4" aria-hidden />
              {t("addToDataset")}
            </DropdownMenuItem>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
      {addingToDataset && (
        <GapToDatasetDialog topicId={topic.id} onClose={() => setAddingToDataset(false)} />
      )}
    </>
  );
}
