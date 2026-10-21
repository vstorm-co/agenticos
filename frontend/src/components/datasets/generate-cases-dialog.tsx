"use client";

import { useState } from "react";
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
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { MoreOptions } from "@/components/ui/more-options";
import { useAgents } from "@/hooks/use-agents";
import { useGenerateCases } from "@/hooks/use-case-generation";
import { usePermissions } from "@/hooks/use-permissions";
import { submitFailure } from "@/lib/api-error";
import { DIALOG_COLUMN, DIALOG_FORM } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import {
  CASE_ORIGINS,
  type CaseGenerationEstimate,
  type CaseGenerationRequest,
  type CaseOrigin,
} from "@/types/case-generation";
import { Perm } from "@/types/permissions";
import { GenerationEstimate } from "./generation-estimate";

const FIELDS = ["agent_id", "sources", "count"] as const;
type Field = (typeof FIELDS)[number];

export const MAX_GENERATED = 50;

interface GenerateCasesDialogProps {
  datasetId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * Ask the case generator for drafts: which agent, from which sources, how many.
 *
 * Two steps, because the second one spends money: an estimate first, then the
 * generation. Changing anything throws the estimate away, so what is started is
 * always what was estimated.
 */
export function GenerateCasesDialog({ datasetId, open, onOpenChange }: GenerateCasesDialogProps) {
  const t = useTranslations("datasets");
  const tErrors = useTranslations("errors");
  const { can } = usePermissions();
  const { agents } = useAgents();
  const { estimate, start } = useGenerateCases(datasetId);
  const [agentId, setAgentId] = useState("");
  const [sources, setSources] = useState<CaseOrigin[]>(["agent", "red_team"]);
  const [count, setCount] = useState(20);
  const [estimated, setEstimated] = useState<CaseGenerationEstimate | null>(null);
  const [errors, setErrors] = useState<Partial<Record<Field, string>>>({});

  const request: CaseGenerationRequest = { agent_id: agentId, sources, count };
  const valid = agentId !== "" && sources.length > 0 && count >= 1 && count <= MAX_GENERATED;
  const changed = () => {
    setEstimated(null);
    setErrors({});
  };

  async function submit(step: "estimate" | "start") {
    try {
      if (step === "estimate") {
        setEstimated(await estimate.mutateAsync(request));
        return;
      }
      await start.mutateAsync(request);
      toast.success(t("generationStarted", { count }));
      onOpenChange(false);
    } catch (error) {
      const failure = submitFailure(error, { fields: [...FIELDS] }, tErrors);
      setErrors(failure.fields);
      if (failure.toast) toast.error(failure.toast);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={cn(DIALOG_COLUMN, DIALOG_FORM)}>
        <DialogHeader>
          <DialogTitle>{t("generateCases")}</DialogTitle>
          <DialogDescription>{t("generateCasesBody")}</DialogDescription>
        </DialogHeader>
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-0.5 py-1">
          <FormField htmlFor="generate-agent" label={t("agent")} error={errors.agent_id} required>
            <Select
              value={agentId}
              onValueChange={(next) => {
                setAgentId(next);
                changed();
              }}
            >
              <SelectTrigger id="generate-agent">
                <SelectValue placeholder={t("chooseAgent")} />
              </SelectTrigger>
              <SelectContent>
                {agents.map((agent) => (
                  <SelectItem key={agent.id} value={agent.id}>
                    {agent.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
          <FormField htmlFor="generate-sources" label={t("sources")} error={errors.sources}>
            <div id="generate-sources" className="space-y-2">
              {CASE_ORIGINS.map((origin) => {
                const locked = origin === "conversation" && !can(Perm.runsView);
                return (
                  <div key={origin} className="flex items-start gap-2">
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
                    <Label htmlFor={`source-${origin}`} className="space-y-0.5 font-normal">
                      <span className="block text-sm">{t(`origin.${origin}`)}</span>
                      <span className="text-muted-foreground block text-xs">
                        {t(locked ? "sourceNeedsRunsView" : `sourceHint.${origin}`)}
                      </span>
                    </Label>
                  </div>
                );
              })}
            </div>
          </FormField>
          {/* Opened by a refusal of the count, so the field it names is in view. */}
          <MoreOptions
            label={t("generateMore", { count })}
            open={errors.count !== undefined ? true : undefined}
          >
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
          </MoreOptions>
          {estimated !== null && <GenerationEstimate estimate={estimated} />}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          {estimated === null ? (
            <Button disabled={!valid || estimate.isPending} onClick={() => void submit("estimate")}>
              {t("estimateCost")}
            </Button>
          ) : (
            <Button disabled={start.isPending} onClick={() => void submit("start")}>
              {t("generate")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
