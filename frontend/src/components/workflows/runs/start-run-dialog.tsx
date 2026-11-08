"use client";

import { useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Label,
  MoreOptions,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { CodeArea } from "@/components/ui/code-area";
import { JsonView } from "@/components/ui/json-view";
import { fieldProblems } from "@/lib/api-error";
import { DIALOG_FORM, DIALOG_SCROLL } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import { type FormValue, type InputField, runInputFrom } from "@/lib/workflows/input-fields";
import type { JsonSchema } from "@/lib/workflows/types";

import { RunField } from "./run-field";

export interface RunEntry {
  id: string;
  name: string;
  fields: readonly InputField[];
  inputSchema?: JsonSchema | null;
  sample: Record<string, unknown>;
}

interface StartRunDialogProps {
  entries?: readonly RunEntry[];
  liveEntries?: readonly RunEntry[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Whether a published version exists to run for real. */
  canRunLive: boolean;
  /** Whether this caller may test the draft (`workflows:edit`). */
  canTest: boolean;
  /** Published-contract loading or failure does not block independent draft tests. */
  liveNotice?: ReactNode;
  busy?: boolean;
  /** Structured admission refusals stay beside the input until it is edited. */
  error?: unknown;
  onInputChange?: () => void;
  /** What the input starts as - the draft's trigger's shape, for a test run. */
  sampleInput?: Record<string, unknown>;
  /** The fields the draft's "Manual or API" trigger declares, asked for by name in a test run. */
  testFields?: readonly InputField[];
  /** The fields the published version's trigger declares, asked for in a real run. */
  liveFields?: readonly InputField[];
  testInputSchema?: JsonSchema | null;
  liveInputSchema?: JsonSchema | null;
  onStart: (start: {
    mode: "real" | "test";
    input: Record<string, unknown>;
    entry_node_id?: string;
  }) => void;
}

/** Parse the input box: a JSON object, or the message saying what is wrong. */
export function parseRunInput(text: string): Record<string, unknown> | string {
  if (text.trim() === "") return {};
  try {
    const value: unknown = JSON.parse(text);
    if (typeof value !== "object" || value === null || Array.isArray(value)) return "notObject";
    return value as Record<string, unknown>;
  } catch {
    return "notJson";
  }
}

/**
 * Start a run by hand - of the draft, to try it, or of the published version.
 *
 * The input is what the trigger hands the graph. When the trigger declares
 * fields, each is asked for by name and typed as declared - the version being
 * run decides which; otherwise it is a JSON object, typed the way an API caller
 * would send it, and prefilled in the draft trigger's shape.
 */
export function StartRunDialog({
  open,
  entries: testEntries = [],
  liveEntries = [],
  onOpenChange,
  canRunLive,
  canTest,
  liveNotice,
  busy,
  error,
  onInputChange,
  sampleInput = {},
  testFields = [],
  liveFields = [],
  testInputSchema = null,
  liveInputSchema = null,
  onStart,
}: StartRunDialogProps) {
  const t = useTranslations("pages.workflows");
  const [mode, setMode] = useState<"real" | "test">(canTest ? "test" : "real");
  const [text, setText] = useState(() => {
    const sample = (canTest ? testEntries : liveEntries)[0]?.sample ?? (canTest ? sampleInput : {});
    return JSON.stringify(sample, null, 2);
  });
  const [values, setValues] = useState<Record<string, FormValue>>({});
  const [tried, setTried] = useState(false);
  const entries = mode === "test" ? testEntries : liveEntries;
  const [entryId, setEntryId] = useState(entries[0]?.id);
  const entry = entries.find((candidate) => candidate.id === entryId) ?? entries[0];
  const fields = entry?.fields ?? (mode === "test" ? testFields : liveFields);
  const inputSchema =
    entry === undefined
      ? mode === "test"
        ? testInputSchema
        : liveInputSchema
      : (entry.inputSchema ?? null);
  const typed = fields.length > 0;
  const parsed = parseRunInput(text);
  const invalid = !typed && typeof parsed === "string";
  const fromForm = runInputFrom(fields, values);
  const problems = tried && "problems" in fromForm ? fromForm.problems : {};
  const refused = fieldProblems(error).filter(
    ({ field }) => field === "input" || field.startsWith("input."),
  );
  const changeOpen = (next: boolean) => {
    if (busy) return;
    if (!next) onInputChange?.();
    onOpenChange(next);
  };

  const submit = () => {
    if (typed) {
      setTried(true);
      if ("input" in fromForm)
        onStart({ mode, input: fromForm.input, ...(entry ? { entry_node_id: entry.id } : {}) });
    } else if (typeof parsed !== "string") {
      onStart({ mode, input: parsed, ...(entry ? { entry_node_id: entry.id } : {}) });
    }
  };

  return (
    <Dialog open={open} onOpenChange={changeOpen}>
      <DialogContent className={cn(DIALOG_FORM, DIALOG_SCROLL)}>
        <DialogHeader>
          <DialogTitle>{t("startRunTitle")}</DialogTitle>
          <DialogDescription>{t("startRunDescription")}</DialogDescription>
        </DialogHeader>
        {liveNotice}
        <fieldset className="space-y-4" disabled={busy}>
          <div className="space-y-1.5">
            <Label htmlFor="run-mode">{t("startRunMode")}</Label>
            <Select
              value={mode}
              onValueChange={(value) => {
                onInputChange?.();
                const nextMode = value === "real" ? "real" : "test";
                const first = (nextMode === "test" ? testEntries : liveEntries)[0];
                setMode(nextMode);
                setEntryId(first?.id);
                setValues({});
                setTried(false);
                setText(
                  JSON.stringify(
                    first?.sample ?? (nextMode === "test" ? sampleInput : {}),
                    null,
                    2,
                  ),
                );
              }}
            >
              <SelectTrigger id="run-mode">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {canTest && <SelectItem value="test">{t("modeTest")}</SelectItem>}
                {(canRunLive || mode === "real") && (
                  <SelectItem value="real" disabled={!canRunLive}>
                    {t("modeReal")}
                  </SelectItem>
                )}
              </SelectContent>
            </Select>
          </div>
          {entries.length > 1 && (
            <div className="space-y-1.5">
              <Label htmlFor="run-entry">{t("startRunEntry")}</Label>
              <Select
                value={entry?.id}
                onValueChange={(id) => {
                  onInputChange?.();
                  setEntryId(id);
                  setValues({});
                  setTried(false);
                  setText(
                    JSON.stringify(
                      entries.find((candidate) => candidate.id === id)?.sample ?? {},
                      null,
                      2,
                    ),
                  );
                }}
              >
                <SelectTrigger id="run-entry">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {entries.map((candidate) => (
                    <SelectItem key={candidate.id} value={candidate.id}>
                      {candidate.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
          {typed ? (
            <div className="space-y-3">
              {fields.map((field) => (
                <RunField
                  key={field.name}
                  field={field}
                  value={values[field.name]}
                  problem={problems[field.name]}
                  onChange={(value) => {
                    onInputChange?.();
                    setValues({ ...values, [field.name]: value });
                  }}
                />
              ))}
            </div>
          ) : (
            <div className="space-y-1.5">
              <Label>{t("startRunInput")}</Label>
              {inputSchema !== null && (
                <MoreOptions label={t("startRunSchema")}>
                  <JsonView value={inputSchema} />
                </MoreOptions>
              )}
              <CodeArea
                name="input.json"
                aria-label={t("startRunInput")}
                value={text}
                onChange={(next) => {
                  onInputChange?.();
                  setText(next);
                }}
                invalid={invalid || refused.length > 0}
                describedBy={refused.length > 0 ? "run-input-errors" : undefined}
                className="min-h-40"
              />
              {typeof parsed === "string" && (
                <p className="text-destructive text-xs">{t(`startRunInputInvalid.${parsed}`)}</p>
              )}
            </div>
          )}
          {refused.length > 0 && (
            <ul id="run-input-errors" role="alert" className="text-destructive space-y-1 text-xs">
              {refused.map((problem, index) => (
                <li key={index} className="break-words">
                  <code>{problem.field}</code>
                  {": "}
                  {problem.message}
                </li>
              ))}
            </ul>
          )}
        </fieldset>
        <DialogFooter>
          <Button variant="outline" disabled={busy} onClick={() => changeOpen(false)}>
            {t("cancel")}
          </Button>
          <Button disabled={invalid || busy || (mode === "real" && !canRunLive)} onClick={submit}>
            {t("startRun")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
