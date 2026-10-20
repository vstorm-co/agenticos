"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { Badge, Button, Card, CardContent, CardHeader, CardTitle } from "@/components/ui";
import { specText } from "@/components/agents/version-history";
import { useAgentVersion } from "@/hooks";
import { useAgentAuthoring } from "@/hooks/use-authoring";
import { useAiAssistance } from "@/hooks/use-organizations";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import type { AgentSpec } from "@/types/agents";
import type { AuthoringKind, Hunk, HunkDecision } from "@/types/authoring";
import { AiOffNotice } from "./ai-off-notice";
import { CheckDialog } from "./check-dialog";
import { ImproveDialog } from "./improve-dialog";
import { SuggestionList } from "./suggestion-list";
import { VerifyReport } from "./verify-report";

/**
 * The authoring assistant on the Build tab: ask it to improve the agent or to
 * verify the draft's edits, check what it suggests with evals, and decide each
 * suggestion. Nothing it suggests reaches the draft without Accept, and nothing
 * reaches anybody without Publish.
 *
 * A decision writes the draft on the server, so the page's own unsaved edit is
 * stored first, and the draft the server answers with replaces the page's.
 */
export function AssistantStrip({
  agentId,
  currentVersionId,
  storedDraft,
  persist,
  onDraft,
}: {
  agentId: string;
  currentVersionId: string | null;
  /** The draft as stored - Verify needs it to differ from the published version. */
  storedDraft: AgentSpec;
  /** Store the page's draft; false when it did not store. */
  persist: () => Promise<boolean>;
  onDraft: (spec: AgentSpec) => void;
}) {
  const t = useTranslations("authoring.strip");
  const tErrors = useTranslations("errors");
  const router = useRouter();
  const { orgId, enabled } = useAiAssistance();
  const assistant = useAgentAuthoring(agentId);
  const [asking, setAsking] = useState<AuthoringKind | null>(null);
  const [checking, setChecking] = useState(false);
  const { authoring, decide } = assistant;
  const { version } = useAgentVersion(agentId, currentVersionId);
  const draftDiffers = useMemo(
    () => version !== undefined && specText(storedDraft) !== specText(version.spec),
    [storedDraft, version],
  );
  const batch = authoring?.batch ?? null;
  const latest = authoring?.latest ?? null;
  const pending =
    batch?.status === "open" ? batch.hunks.filter((hunk) => hunk.status === "pending") : [];
  const working = latest?.status === "queued" || latest?.status === "running";
  const off = enabled === false;

  async function onDecide(hunk: Hunk, decision: HunkDecision) {
    if (!(await persist())) return;
    try {
      const decided = await decide.mutateAsync({ hunkId: hunk.id, ...decision });
      onDraft(decided.draft_spec);
    } catch (failure) {
      toast.error(getErrorMessage(failure, tErrors));
    }
  }

  return (
    <Card data-tour="agent-assistant-strip">
      <CardHeader className="flex-row flex-wrap items-center gap-3 space-y-0">
        <Sparkles className="text-primary h-5 w-5" aria-hidden />
        <CardTitle className="flex-1">{t("title")}</CardTitle>
        {pending.length > 0 && (
          <Badge>
            {t("chip", {
              count: pending.length,
              ratedDown: latest?.evidence.rated_down ?? 0,
              runs: latest?.evidence.runs ?? 0,
            })}
          </Badge>
        )}
        <div className="flex flex-wrap gap-2">
          <Button size="sm" disabled={off || working} onClick={() => setAsking("improve")}>
            {working ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
            {working ? t("working") : t("improve")}
          </Button>
          {draftDiffers && (
            <Button
              size="sm"
              variant="outline"
              disabled={off || working}
              onClick={() => setAsking("verify")}
            >
              {t("verify")}
            </Button>
          )}
          {pending.length > 0 && (
            <>
              <Button size="sm" variant="outline" onClick={() => setChecking(true)}>
                {t("check")}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                disabled={assistant.dismissAll.isPending}
                onClick={() => assistant.dismissAll.mutate()}
              >
                {t("dismissAll")}
              </Button>
            </>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {off && orgId !== null && <AiOffNotice orgId={orgId} />}
        {latest?.status === "failed" && (
          <p role="alert" className="text-destructive text-sm">
            {latest.error}
          </p>
        )}
        {!working && batch === null && latest === null && (
          <p className="text-muted-foreground text-sm">{t("empty")}</p>
        )}
        {batch !== null && (
          <SuggestionList
            batch={batch}
            agentId={agentId}
            busy={decide.isPending}
            onDecide={onDecide}
          />
        )}
        {authoring?.verify?.report?.findings !== undefined && (
          <details>
            <summary className="cursor-pointer text-sm font-medium">{t("verifyReport")}</summary>
            <div className="pt-3">
              <VerifyReport findings={authoring.verify.report.findings} />
            </div>
          </details>
        )}
      </CardContent>
      {asking !== null && (
        <ImproveDialog
          kind={asking}
          estimate={assistant.estimate.mutateAsync}
          start={assistant.start.mutateAsync}
          onOpenChange={(open) => !open && setAsking(null)}
        />
      )}
      {checking && (
        <CheckDialog
          agentId={agentId}
          estimate={assistant.checkEstimate.mutateAsync}
          start={assistant.check.mutateAsync}
          onStarted={(run) => router.push(`${ROUTES.AGENTS}/${agentId}/evals/${run.id}`)}
          onOpenChange={setChecking}
        />
      )}
    </Card>
  );
}
