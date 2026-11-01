"use client";

import { useState } from "react";
import Link from "next/link";
import { CheckCircle2, CircleDashed, FlaskConical, Plus, Trash2, XCircle } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Button,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useStepEvals } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { formatCostUsd } from "@/lib/utils";
import { knownInput, knownOutputs } from "@/lib/workflows/step-data";
import type {
  EvalCase,
  EvalExpectation,
  EvalResult,
  NodeInstance,
  WorkflowGraph,
} from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

/** The steps whose answer a model writes - `MODEL_STEPS` in `workflow_evals.py`. */
export const MODEL_STEPS: ReadonlySet<string> = new Set([
  "agent.run",
  "ai.prompt",
  "ai.classify",
  "ai.extract",
  "ai.rewrite",
  "decide.choose",
  "decide.yes_no",
  "decide.score",
]);

const KINDS: EvalExpectation["kind"][] = ["contains", "not_contains", "equals"];

function usd(amount: number): string {
  return formatCostUsd(amount);
}

/**
 * A model step's evals: the cases it should handle, and trying them all.
 *
 * A case is written from the input the step was last tested with - the run's
 * input and what the steps before it handed on - so it is the real shape of the
 * data, never typed out by hand. Trying the cases starts a test run of the step
 * for each, and each one's verdict lands as its run ends.
 */
export function StepEvals({
  workflowId,
  graph,
  node,
}: {
  workflowId: string;
  graph: WorkflowGraph;
  node: NodeInstance;
}) {
  const t = useTranslations("workflows.evals");
  const stepData = useWorkflowEditorStore((state) => state.stepData);
  const { cases, latest, isLoading, create, remove, run } = useStepEvals(workflowId, node.id);
  const [adding, setAdding] = useState(false);
  const outputs = knownOutputs(graph, node.id, stepData);
  const tested = Object.keys(outputs).length > 0;

  const results = new Map(latest?.results.map((result) => [result.eval_id, result]) ?? []);

  return (
    <div className="space-y-5">
      <div className="space-y-1">
        <p className="text-muted-foreground text-xs">{t("intro")}</p>
      </div>

      {latest !== null && (
        <div className="bg-muted/40 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg px-3 py-2 text-sm">
          <span className="font-medium">
            {t("summary", { passed: latest.passed, total: latest.results.length })}
          </span>
          {latest.pending > 0 && (
            <span className="text-muted-foreground text-xs">
              {t("pending", { count: latest.pending })}
            </span>
          )}
          <span className="text-muted-foreground text-xs">{usd(latest.cost_usd)}</span>
        </div>
      )}

      {isLoading ? null : cases.length === 0 ? (
        <p className="text-muted-foreground rounded-lg border border-dashed p-4 text-center text-sm">
          {t("none")}
        </p>
      ) : (
        <ul className="divide-border divide-y rounded-lg border">
          {cases.map((one) => (
            <CaseRow
              key={one.id}
              workflowId={workflowId}
              item={one}
              result={results.get(one.id)}
              removing={remove.isPending}
              onRemove={() => remove.mutate(one.id)}
            />
          ))}
        </ul>
      )}

      <div className="flex flex-wrap gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={() => setAdding(true)}
          disabled={adding || !tested}
        >
          <Plus className="h-4 w-4" />
          {t("add")}
        </Button>
        <Button
          size="sm"
          onClick={() => run.mutate()}
          disabled={cases.length === 0 || run.isPending || (latest?.pending ?? 0) > 0}
        >
          <FlaskConical className="h-4 w-4" />
          {t("run", { count: cases.length })}
        </Button>
      </div>
      {!tested && <p className="text-muted-foreground text-xs">{t("testFirst")}</p>}

      {adding && (
        <CaseForm
          saving={create.isPending}
          onCancel={() => setAdding(false)}
          onSave={(name, expectation) =>
            create.mutate(
              {
                name,
                expectation,
                outputs,
                run_input: knownInput(graph, stepData) ?? {},
              },
              { onSuccess: () => setAdding(false) },
            )
          }
        />
      )}
    </div>
  );
}

function CaseRow({
  workflowId,
  item,
  result,
  removing,
  onRemove,
}: {
  workflowId: string;
  item: EvalCase;
  result: EvalResult | undefined;
  removing: boolean;
  onRemove: () => void;
}) {
  const t = useTranslations("workflows.evals");
  const { kind, field, value } = item.expectation;
  const Verdict =
    result === undefined
      ? null
      : result.passed === null
        ? CircleDashed
        : result.passed
          ? CheckCircle2
          : XCircle;

  return (
    <li className="flex items-start gap-3 p-3">
      <span className="mt-0.5 w-4 shrink-0">
        {Verdict !== null && (
          <Verdict
            aria-label={t(
              result?.passed === null
                ? "verdictPending"
                : result?.passed
                  ? "verdictPassed"
                  : "verdictFailed",
            )}
            className={
              result?.passed === null
                ? "text-muted-foreground h-4 w-4 animate-spin"
                : result?.passed
                  ? "h-4 w-4 text-emerald-600"
                  : "text-destructive h-4 w-4"
            }
          />
        )}
      </span>
      <div className="min-w-0 flex-1 space-y-1">
        <p className="text-sm font-medium">{item.name}</p>
        <p className="text-muted-foreground text-xs">
          {t("expects", { field: field ?? t("wholeOutput"), kind: t(`kind.${kind}`), value })}
        </p>
        {result?.actual != null && (
          <p className="text-muted-foreground truncate text-xs">
            {t("said", { actual: result.actual || t("nothing") })}
          </p>
        )}
        {result?.reason != null && <p className="text-destructive text-xs">{result.reason}</p>}
        {result?.workflow_run_id != null && (
          <Link
            href={ROUTES.WORKFLOW_RUN_DETAIL(workflowId, result.workflow_run_id)}
            className="text-muted-foreground text-xs underline underline-offset-2"
          >
            {t("openRun")}
          </Link>
        )}
      </div>
      <Button
        variant="ghost"
        size="icon"
        aria-label={t("remove", { name: item.name })}
        disabled={removing}
        onClick={onRemove}
      >
        <Trash2 className="h-4 w-4" />
      </Button>
    </li>
  );
}

function CaseForm({
  saving,
  onCancel,
  onSave,
}: {
  saving: boolean;
  onCancel: () => void;
  onSave: (name: string, expectation: EvalExpectation) => void;
}) {
  const t = useTranslations("workflows.evals");
  const [name, setName] = useState("");
  const [kind, setKind] = useState<EvalExpectation["kind"]>("contains");
  const [field, setField] = useState("text");
  const [value, setValue] = useState("");
  const ready = name.trim() !== "" && value.trim() !== "";

  return (
    <div className="space-y-3 rounded-lg border p-3">
      <p className="text-muted-foreground text-xs">{t("fromLastTest")}</p>
      <div className="space-y-1.5">
        <Label htmlFor="eval-name">{t("name")}</Label>
        <Input
          id="eval-name"
          value={name}
          maxLength={120}
          placeholder={t("namePlaceholder")}
          onChange={(event) => setName(event.target.value)}
        />
      </div>
      <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div className="space-y-1.5">
          <Label htmlFor="eval-field">{t("field")}</Label>
          <Input
            id="eval-field"
            value={field}
            maxLength={200}
            className="font-mono"
            placeholder={t("wholeOutput")}
            onChange={(event) => setField(event.target.value)}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="eval-kind">{t("kindLabel")}</Label>
          <Select value={kind} onValueChange={(next) => setKind(next as EvalExpectation["kind"])}>
            <SelectTrigger id="eval-kind">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {KINDS.map((one) => (
                <SelectItem key={one} value={one}>
                  {t(`kind.${one}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="eval-value">{t("value")}</Label>
        <Input
          id="eval-value"
          value={value}
          maxLength={2000}
          placeholder={t("valuePlaceholder")}
          onChange={(event) => setValue(event.target.value)}
        />
      </div>
      <div className="flex justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={onCancel}>
          {t("cancel")}
        </Button>
        <Button
          size="sm"
          disabled={!ready || saving}
          onClick={() =>
            onSave(name.trim(), { kind, field: field.trim() || null, value: value.trim() })
          }
        >
          {t("save")}
        </Button>
      </div>
    </div>
  );
}
