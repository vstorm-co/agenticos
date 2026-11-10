"use client";

import { AlertCircle } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button, Card, CardContent } from "@/components/ui";
import type { SpecFix } from "@/lib/spec-fixes";

const FIX_LABEL: Record<SpecFix, string> = {
  use_state_workspace: "fixUseStateWorkspace",
  stop_sharing_unbound: "fixStopSharingUnbound",
};

interface PublishRefusalProps {
  problems: string[];
  fixes: SpecFix[];
  /** Whether the reader may change the draft a fix rewrites. */
  canEdit: boolean;
  /** Applies the fix to the draft, saves it and checks it again. Never publishes. */
  onFix: (fix: SpecFix) => void;
  fixing: boolean;
  /** Whether a problem is the missing model, which has a card to jump to. */
  isModelProblem: (problem: string) => boolean;
  onGoToModel: () => void;
}

/** Why the draft cannot be published, and the one-click fixes the server offered for it. */
export function PublishRefusal({
  problems,
  fixes,
  canEdit,
  onFix,
  fixing,
  isModelProblem,
  onGoToModel,
}: PublishRefusalProps) {
  const t = useTranslations("pages.agents");
  const offered = canEdit ? fixes : [];

  return (
    <Card className="border-destructive/40 bg-destructive/5">
      <CardContent className="space-y-2 p-4">
        <p className="flex items-center gap-2 text-sm font-medium">
          <AlertCircle className="h-4 w-4" />
          {t("agentCannotBePublished")}
        </p>
        <ul className="text-muted-foreground list-inside list-disc space-y-1 text-sm">
          {problems.map((problem) => (
            <li key={problem}>
              {problem}
              {isModelProblem(problem) && (
                <Button variant="link" size="sm" className="ml-2 h-auto p-0" onClick={onGoToModel}>
                  {t("goToModel")}
                </Button>
              )}
            </li>
          ))}
        </ul>
        {offered.length > 0 && (
          <div className="space-y-2 pt-1">
            <div className="flex flex-wrap gap-2">
              {offered.map((fix) => (
                <Button
                  key={fix}
                  size="sm"
                  variant="outline"
                  disabled={fixing}
                  onClick={() => onFix(fix)}
                >
                  {t(FIX_LABEL[fix])}
                </Button>
              ))}
            </div>
            <p className="text-muted-foreground text-xs">{t("fixSavesTheDraft")}</p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
