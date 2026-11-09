"use client";

import { useId, useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import {
  Button,
  Checkbox,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  FormField,
  Input,
} from "@/components/ui";
import { AgentSelect } from "@/components/agents/agent-select";
import { useAgents } from "@/hooks/use-agents";
import { useGenerateCases } from "@/hooks/use-case-generation";
import { usePermissions } from "@/hooks/use-permissions";
import { useUnsavedChanges } from "@/hooks/use-unsaved-changes";
import { getErrorMessage, submitFailure } from "@/lib/api-error";
import { DIALOG_BODY, DIALOG_COLUMN, DIALOG_WIDE } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import { useUnsavedChangesStore } from "@/stores/unsaved-changes-store";
import {
  CASE_ORIGINS,
  type CaseGenerationEstimate,
  type CaseGenerationRequest,
  type CaseOrigin,
} from "@/types/case-generation";
import { Perm } from "@/types/permissions";
import { GenerationEstimate } from "./generation-estimate";

const FIELDS = ["agent_id", "sources", "count"] as const;
const DEFAULT_SOURCES: CaseOrigin[] = ["agent", "red_team"];
const DEFAULT_COUNT = 20;
type Field = (typeof FIELDS)[number];

export const MAX_GENERATED = 50;

interface GenerateCasesDialogProps {
  datasetId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onStarted?: () => void;
  /** What the form opens with, when the caller already knows the agent and how many. */
  initial?: { agentId: string; count: number };
}

/**
 * Ask the case generator for drafts: which agent, from which sources, how many.
 *
 * Two steps, because the second one spends money: an estimate first, then the
 * generation. Changing anything throws the estimate away, so what is started is
 * always what was estimated.
 */
export function GenerateCasesDialog({
  datasetId,
  open,
  onOpenChange,
  initial,
  onStarted,
}: GenerateCasesDialogProps) {
  const t = useTranslations("datasets");
  const tErrors = useTranslations("errors");
  const { can } = usePermissions();
  const { agents, isLoading: agentsLoading, error: agentsError, refetch } = useAgents();
  const tc = useTranslations("common");
  const { estimate, start } = useGenerateCases(datasetId);
  const [agentId, setAgentId] = useState(initial?.agentId ?? "");
  const [sources, setSources] = useState<CaseOrigin[]>(DEFAULT_SOURCES);
  const [count, setCount] = useState(initial?.count ?? DEFAULT_COUNT);
  const [quote, setQuote] = useState<{ key: string; value: CaseGenerationEstimate } | null>(null);
  const [errors, setErrors] = useState<Partial<Record<Field, string>>>({});

  const request: CaseGenerationRequest = {
    agent_id: agentId,
    sources,
    count,
  };
  const requestKey = `${datasetId}:${JSON.stringify(request)}`;
  const estimated = quote?.key === requestKey ? quote.value : null;
  const valid =
    !agentsError &&
    !agentsLoading &&
    agentId !== "" &&
    sources.length > 0 &&
    Number.isInteger(count) &&
    count >= 1 &&
    count <= MAX_GENERATED;
  const changed = () => {
    setQuote(null);
    setErrors({});
  };
  // Starting spends, so leaving offers no Save: only discarding the choices or staying.
  const source = useId();
  useUnsavedChanges(source, {
    dirty:
      open &&
      (agentId !== (initial?.agentId ?? "") ||
        sources.join() !== DEFAULT_SOURCES.join() ||
        count !== (initial?.count ?? DEFAULT_COUNT)),
    discard: () => onOpenChange(false),
  });
  // Only ever asked to close: it has no trigger of its own.
  const close = () => useUnsavedChangesStore.getState().leave(() => onOpenChange(false), [source]);

  async function submit(step: "estimate" | "start") {
    try {
      if (step === "estimate") {
        setQuote({ key: requestKey, value: await estimate.mutateAsync(request) });
        return;
      }
      await start.mutateAsync(request);
      toast.success(t("generationStarted", { count }));
      onOpenChange(false);
      onStarted?.();
    } catch (error) {
      const failure = submitFailure(error, { fields: [...FIELDS] }, tErrors);
      setErrors(failure.fields);
      if (failure.toast) toast.error(failure.toast);
    }
  }

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className={cn(DIALOG_COLUMN, DIALOG_WIDE)}>
        <DialogHeader>
          <DialogTitle>{t("generateCases")}</DialogTitle>
          <DialogDescription>{t("generateCasesBody")}</DialogDescription>
        </DialogHeader>
        <div className={cn(DIALOG_BODY, "space-y-6")}>
          <p className="text-muted-foreground text-sm">{t("helpers.generationUsesSettings")}</p>
          {agentsError && (
            <div role="alert" className="space-y-2 text-sm">
              <p className="text-destructive-ink">{getErrorMessage(agentsError, tErrors)}</p>
              <Button variant="outline" size="sm" onClick={() => void refetch()}>
                {tc("retry")}
              </Button>
            </div>
          )}
          <FormField
            htmlFor="generate-agent"
            label={t("agent")}
            description={t("agentHint")}
            error={errors.agent_id}
            required
          >
            <AgentSelect
              id="generate-agent"
              agents={agents}
              value={agentId}
              loading={agentsLoading}
              placeholder={t("chooseAgent")}
              onChange={(next) => {
                setAgentId(next);
                changed();
              }}
            />
          </FormField>
          <FormField htmlFor="generate-sources" label={t("sources")} error={errors.sources}>
            <div id="generate-sources" className="grid gap-3 sm:grid-cols-2">
              {CASE_ORIGINS.map((origin) => {
                const locked = origin === "conversation" && !can(Perm.runsView);
                return (
                  <label
                    key={origin}
                    htmlFor={`source-${origin}`}
                    className={cn(
                      "has-[:focus-visible]:ring-ring flex cursor-pointer items-start gap-3 rounded-xl border p-4 transition-colors has-[:focus-visible]:ring-2",
                      sources.includes(origin) && "border-foreground/30 bg-accent/40",
                      locked ? "cursor-not-allowed opacity-50" : "hover:bg-accent/40",
                    )}
                  >
                    <Checkbox
                      id={`source-${origin}`}
                      disabled={locked}
                      checked={sources.includes(origin)}
                      onCheckedChange={(checked) => {
                        setSources((current) =>
                          checked === true
                            ? CASE_ORIGINS.filter((o) => o === origin || current.includes(o))
                            : current.filter((o) => o !== origin),
                        );
                        changed();
                      }}
                    />
                    <span className="space-y-0.5 text-sm font-medium">
                      {t(`origin.${origin}`)}
                      <span className="text-muted-foreground block text-xs font-normal">
                        {t(locked ? "sourceNeedsRunsView" : `sourceHint.${origin}`)}
                      </span>
                    </span>
                  </label>
                );
              })}
            </div>
          </FormField>
          <FormField
            htmlFor="generate-count"
            label={t("caseNumber")}
            description={t("caseNumberHint", { max: MAX_GENERATED })}
            error={errors.count}
          >
            <Input
              id="generate-count"
              type="number"
              min={1}
              max={MAX_GENERATED}
              value={count}
              onChange={(event) => {
                setCount(Number(event.target.value));
                changed();
              }}
            />
          </FormField>
          {estimated !== null && <GenerationEstimate estimate={estimated} />}
        </div>
        <DialogFooter className="border-t">
          <Button variant="outline" onClick={close}>
            {t("cancel")}
          </Button>
          {estimated === null ? (
            <Button
              loading={estimate.isPending}
              disabled={!valid || estimate.isPending}
              onClick={() => void submit("estimate")}
            >
              {t("estimateCost")}
            </Button>
          ) : (
            <Button
              loading={start.isPending}
              disabled={start.isPending}
              onClick={() => void submit("start")}
            >
              {t("generate")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
