"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { ImproveButton } from "@/components/agents/improve-link";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle } from "@/components/ui";
import { NeedsRunsView } from "@/components/evals/needs-runs-view";
import { specText } from "@/components/agents/version-history";
import { useDraftBase } from "@/hooks";
import { useAgentAuthoring } from "@/hooks/use-authoring";
import { useAiAssistance } from "@/hooks/use-organizations";
import { usePermissions } from "@/hooks/use-permissions";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import type { AgentSpec } from "@/types/agents";
import { ideaState } from "@/lib/authoring-groups";
import type { AuthoringRequest, Hunk, HunkDecision, ProposedSkill } from "@/types/authoring";
import { Perm } from "@/types/permissions";
import { AiOffNotice } from "./ai-off-notice";
import { CheckDialog } from "./check-dialog";
import { ImproveDialog } from "./improve-dialog";
import { SuggestionList } from "./suggestion-list";
import { RejectedChanges } from "./rejected-changes";
import { VerifyReport } from "./verify-report";
import { AuthoringResultNotice } from "./result-dialog";

/**
 * The authoring assistant on the Build tab: open the Improve wizard, ask it to
 * verify the draft's edits, check what it suggests with evals, and decide each
 * suggestion. Nothing it suggests reaches the draft without Accept, and nothing
 * reaches anybody without Publish.
 *
 * A decision writes the draft on the server, so the page's own unsaved edit is
 * stored first, and the draft the server answers with replaces the page's.
 */
export function AssistantStrip({
  agentId,
  storedDraft,
  canCheck,
  checkNeedsRunsView = false,
  persist,
  onDraft,
}: {
  agentId: string;
  /** The draft as stored - Verify needs it to differ from the version it is based on. */
  storedDraft: AgentSpec;
  /** Whether this caller may run the draft on a dataset, which checking does. */
  canCheck: boolean;
  /** Whether it could, but for reading runs - the check is then shown disabled, saying so. */
  checkNeedsRunsView?: boolean;
  /** Store the page's draft; false when it did not store. */
  persist: () => Promise<boolean>;
  onDraft: (spec: AgentSpec) => void;
}) {
  const t = useTranslations("authoring.strip");
  const tErrors = useTranslations("errors");
  const router = useRouter();
  const { orgId, enabled } = useAiAssistance();
  // The assistant reads runs, and checking runs an eval whose results are runs:
  // without runs:view, a person decides what waits but cannot ask for more.
  const { can } = usePermissions();
  const canAsk = can(Perm.runsView);
  const assistant = useAgentAuthoring(agentId);
  const [verifying, setVerifying] = useState(false);
  const [checking, setChecking] = useState(false);
  const { authoring, decide } = assistant;
  const { base } = useDraftBase(agentId);
  const draftDiffers = useMemo(
    () => base !== undefined && specText(storedDraft) !== specText(base.spec),
    [storedDraft, base],
  );
  const batch = authoring?.batch ?? null;
  const latest = authoring?.latest ?? null;
  const pending =
    batch?.status === "open" ? batch.hunks.filter((hunk) => hunk.status === "pending") : [];
  const working = latest?.status === "queued" || latest?.status === "running";
  // Until the latest request is known, a click could start a second one beside it.
  const unknown = assistant.isLoading || assistant.error !== null;
  const off = enabled === false;
  const compact = authoring?.has_evidence === false && batch === null && latest === null;

  async function onDecide(hunk: Hunk, decision: HunkDecision) {
    if (!(await persist())) return;
    try {
      const decided = await decide.mutateAsync({ hunkId: hunk.id, ...decision });
      onDraft(decided.draft_spec);
    } catch (failure) {
      toast.error(getErrorMessage(failure, tErrors));
    }
  }

  async function createSkill(requestId: string, index: number, skill: ProposedSkill) {
    if (!(await persist())) return false;
    const created = await assistant.createSkill.mutateAsync({ requestId, index, ...skill });
    onDraft(created.draft_spec);
    toast.success(t("skillCreated", { name: skill.name }));
    return true;
  }
  const onCreateSkill = can(Perm.skillsEdit) ? createSkill : undefined;
  const finished = latest?.status === "completed" ? latest : null;

  function onDecideIdea(requestId: string, index: number, action: "dismiss" | "undo") {
    assistant.decideIdea.mutate(
      { requestId, index, action },
      { onError: (failure) => toast.error(getErrorMessage(failure, tErrors)) },
    );
  }

  return (
    <Card data-tour="agent-assistant-strip">
      <CardHeader className="flex-row flex-wrap items-center gap-3 space-y-0">
        <Sparkles className="text-primary h-5 w-5" aria-hidden />
        <CardTitle className="flex-1">{t("title")}</CardTitle>
        {pending.length > 0 && (
          <Badge className="whitespace-normal">
            {t("chip", {
              count: pending.length,
              ratedDown: latest?.evidence.rated_down ?? 0,
              runs: latest?.evidence.runs ?? 0,
            })}
          </Badge>
        )}
        <div className="flex flex-wrap gap-2">
          {canAsk && <ImproveButton agentId={agentId} persist={persist} size="sm" />}
          {canAsk && draftDiffers && (
            <Button
              size="sm"
              variant="outline"
              disabled={off || working || unknown}
              onClick={() => setVerifying(true)}
            >
              {t("verify")}
            </Button>
          )}
          {pending.length > 0 && (
            <>
              {canAsk && canCheck && (
                <Button size="sm" variant="outline" onClick={() => setChecking(true)}>
                  {t("check")}
                </Button>
              )}
              {checkNeedsRunsView && (
                <NeedsRunsView size="sm" variant="outline">
                  {t("check")}
                </NeedsRunsView>
              )}
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
      {!compact && (
        <CardContent className="space-y-4">
          {off && orgId !== null && <AiOffNotice orgId={orgId} />}
          {latest?.status === "failed" && (
            <p role="alert" className="text-destructive text-sm">
              {latest.error}
            </p>
          )}
          {working && (
            <p role="status" className="text-muted-foreground text-sm">
              {t("working")}
            </p>
          )}
          {!working && batch === null && latest === null && (
            <p className="text-muted-foreground text-sm">{t("empty")}</p>
          )}
          <SuggestionList
            batch={batch}
            request={finished}
            agentId={agentId}
            actions={{
              busy: decide.isPending || assistant.decideIdea.isPending,
              onDecide,
              instructions: storedDraft.instructions,
              onCreateIdea: onCreateSkill,
              onDecideIdea,
            }}
          />
          {latest !== null && (
            <AuthoringResultNotice
              key={`${orgId}:${agentId}:${latest.id}`}
              request={latest}
              batch={batch}
              canReadRuns={canAsk}
              onCreateSkill={onCreateSkill}
            />
          )}
          {finished && <RejectedChanges report={withoutIdeas(finished.report)} />}
          {authoring?.verify?.report?.findings !== undefined && (
            <details>
              <summary className="cursor-pointer text-sm font-medium">{t("verifyReport")}</summary>
              <div className="pt-3">
                <VerifyReport findings={authoring.verify.report.findings} />
              </div>
            </details>
          )}
        </CardContent>
      )}
      {verifying && (
        <ImproveDialog
          kind="verify"
          estimate={assistant.estimate.mutateAsync}
          start={assistant.start.mutateAsync}
          onOpenChange={(open) => !open && setVerifying(false)}
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

/** A report without its new-skill ideas, which the tabs list as decisions. */
function withoutIdeas(report: AuthoringRequest["report"]): AuthoringRequest["report"] {
  if (!report?.rejected) return report;
  return { ...report, rejected: report.rejected.filter((item) => ideaState(item) === null) };
}
