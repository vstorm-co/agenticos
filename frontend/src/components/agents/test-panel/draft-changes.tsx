"use client";

import { useTranslations } from "next-intl";

import { SpecDiff } from "@/components/agents/version-history";
import { ErrorState, LoadingState } from "@/components/states";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import { useAgentVersion } from "@/hooks";
import { getErrorMessage } from "@/lib/api-error";
import { DIALOG_SCROLL, DIALOG_WIDE } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import type { AgentSpec } from "@/types/agents";

/**
 * What the draft under test changes against the published version (#2074).
 *
 * The same YAML diff as the version history, so a reader trying the draft can
 * see what they are trying before asking why it answers differently. Mounted
 * only while open, so the version is fetched only when somebody asks.
 */
export function DraftChanges({
  agentId,
  versionId,
  draftSpec,
  onClose,
}: {
  agentId: string;
  versionId: string;
  draftSpec: AgentSpec;
  onClose: () => void;
}) {
  const t = useTranslations("agents");
  const tErrors = useTranslations("errors");
  const { version, isLoading, error } = useAgentVersion(agentId, versionId);

  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className={cn(DIALOG_WIDE, DIALOG_SCROLL)}>
        <DialogHeader>
          <DialogTitle>{t("testPanelChangesTitle")}</DialogTitle>
          <DialogDescription>
            {t("testPanelChangesWhy", { version: version?.version ?? 0 })}
          </DialogDescription>
        </DialogHeader>
        {error ? (
          <ErrorState description={getErrorMessage(error, tErrors)} />
        ) : isLoading || !version ? (
          <LoadingState variant="skeleton-list" rows={4} />
        ) : (
          <SpecDiff before={version.spec} after={draftSpec} />
        )}
      </DialogContent>
    </Dialog>
  );
}
