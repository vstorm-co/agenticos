"use client";

import { useState } from "react";
import { EyeOff, FlaskConical, RotateCcw } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { useSetKnowledgeGapStatus } from "@/hooks/use-knowledge-gaps";
import { usePermissions } from "@/hooks/use-permissions";
import { Perm } from "@/types/permissions";
import type { KnowledgeGapTopic } from "@/types/knowledge-gaps";
import { GapToDatasetDialog } from "./gap-to-dataset-dialog";

/**
 * What a person may do with a topic. Each control is left out for a caller
 * whose role cannot use it; the server still decides per knowledge base and
 * per dataset, and answers 404 where a grant does not reach.
 */
export function KnowledgeGapActions({ topic }: { topic: KnowledgeGapTopic }) {
  const t = useTranslations("knowledgeGaps");
  const { can } = usePermissions();
  const setStatus = useSetKnowledgeGapStatus();
  const [addingToDataset, setAddingToDataset] = useState(false);
  const mayEdit = can(Perm.collectionsEdit);
  const mayAddCases = can(Perm.datasetsEdit);
  if (!mayEdit && !mayAddCases) return null;

  const dismissed = topic.status === "dismissed";
  return (
    <div className="flex flex-wrap gap-2">
      {mayEdit && (
        <Button
          variant="outline"
          size="sm"
          disabled={setStatus.isPending}
          onClick={() =>
            setStatus.mutate({ topicId: topic.id, status: dismissed ? "open" : "dismissed" })
          }
        >
          {dismissed ? (
            <RotateCcw className="h-3.5 w-3.5" aria-hidden />
          ) : (
            <EyeOff className="h-3.5 w-3.5" aria-hidden />
          )}
          {dismissed ? t("reopen") : t("dismiss")}
        </Button>
      )}
      {mayAddCases && (
        <Button variant="outline" size="sm" onClick={() => setAddingToDataset(true)}>
          <FlaskConical className="h-3.5 w-3.5" aria-hidden />
          {t("addToDataset")}
        </Button>
      )}
      {addingToDataset && (
        <GapToDatasetDialog topicId={topic.id} onClose={() => setAddingToDataset(false)} />
      )}
    </div>
  );
}
