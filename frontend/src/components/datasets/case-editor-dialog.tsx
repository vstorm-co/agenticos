"use client";

import { useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  FormField,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
} from "@/components/ui";
import { submitFailure } from "@/lib/api-error";
import { DIALOG_COLUMN, DIALOG_WIDE } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import type { DatasetCase, DatasetCaseContent, ToolOrderMode } from "@/types/datasets";
import type { DatasetScoring } from "@/types/scoring";
import { CaseCallsEditor } from "./case-calls-editor";
import { CaseChecksEditor } from "./case-checks-editor";
import { CaseGradedBy } from "./case-graded-by";
import { CaseTwinNotice } from "./case-twin-notice";
import {
  CASE_FIELDS,
  contentOf,
  draftOf,
  expectsSomething,
  type CaseDraft,
  type CaseField,
} from "./case-form";
import { CaseHistoryEditor } from "./case-history-editor";
import { CaseView } from "./case-view";

interface CaseEditorDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The fields to start from: blank for a new case, the case's own for an edit. */
  initial: CaseDraft;
  /** Absent for a case that is only read - an older version, or no edit access. */
  onSave?: (content: DatasetCaseContent) => Promise<unknown>;
  /** A stored case, opened to be read first; absent for a new case, opened to be written. */
  viewing?: DatasetCaseContent;
  title: string;
  /** The version a save makes. */
  nextVersion?: number;
  /** The dataset's Grading, to say what would grade the case as written. */
  scoring?: DatasetScoring;
  /** Tool names the dataset's cases already expect. */
  knownTools?: string[];
  /**
   * For a new case: `find` reads the case already asking its question, if one
   * does, and `open` shows that case in place of the new one.
   */
  twins?: {
    find: (input: string) => Promise<DatasetCase | null>;
    open: (twin: DatasetCase) => void;
  };
}

const ORDER_MODES: ToolOrderMode[] = ["any", "in_order", "exact"];

/** What a case written as JSON holds when it leaves a field out. */
const EMPTY_CONTENT: DatasetCaseContent = {
  input: "",
  history: [],
  reference_answer: null,
  counter_example: null,
  expected_tool_calls: [],
  order_mode: "any",
  checks: [],
  tags: [],
  note: null,
};

type TextField = "input" | "reference_answer" | "counter_example" | "note";
type Slot =
  | { field: TextField; rows: number }
  | "history"
  | "expected_tool_calls"
  | "checks"
  | "tags"
  | "order_mode";

/**
 * The fields in the groups a person thinks in, each a `data-tour` the guided
 * creation stops on: what is asked, what a good and a bad answer are, the tools,
 * the checks, and the labels.
 */
const GROUPS: { group: string; slots: Slot[] }[] = [
  {
    group: "question",
    slots: [{ field: "input", rows: 3 }, "history"],
  },
  {
    group: "answers",
    slots: [
      { field: "reference_answer", rows: 3 },
      { field: "counter_example", rows: 3 },
    ],
  },
  { group: "tools", slots: ["expected_tool_calls", "order_mode"] },
  { group: "checks", slots: ["checks"] },
  { group: "labels", slots: ["tags", { field: "note", rows: 2 }] },
];

/** A structured field, edited as a list of rows under its label. */
function ListField({
  field,
  error,
  children,
}: {
  field: "history" | "expected_tool_calls" | "checks";
  error?: string;
  children: ReactNode;
}) {
  const t = useTranslations("datasets");
  return (
    <fieldset className="space-y-2">
      <legend className="text-sm font-medium">{t(`field.${field}`)}</legend>
      <p className="text-muted-foreground text-xs">{t(`hint.${field}`)}</p>
      {children}
      {error && <p className="text-destructive text-xs">{error}</p>}
    </fieldset>
  );
}

/**
 * One case, read or written.
 *
 * A stored case opens as it reads; Edit turns it into the form. Saving an edit
 * is a new version of the dataset, and the dialog says so: the case a past eval
 * run answered is still there in the version it ran against.
 */
export function CaseEditorDialog({
  open,
  onOpenChange,
  initial,
  onSave,
  viewing,
  title,
  nextVersion,
  scoring,
  knownTools,
  twins,
}: CaseEditorDialogProps) {
  const t = useTranslations("datasets");
  const tErrors = useTranslations("errors");
  const [draft, setDraft] = useState(initial);
  const [errors, setErrors] = useState<Partial<Record<CaseField, string>>>({});
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState(viewing === undefined);
  // The whole case as JSON, while it is edited that way; null in the form.
  const [json, setJson] = useState<string | null>(null);
  const [jsonProblem, setJsonProblem] = useState(false);
  // A case already asking the question, and what to do about it; `repeat` once the
  // person chose to add the new one anyway.
  const [twin, setTwin] = useState<{
    found: DatasetCase;
    open: () => void;
    addAnyway: () => void;
  } | null>(null);
  const [repeat, setRepeat] = useState(false);
  const readOnly = onSave === undefined || !editing;
  const missing =
    json !== null
      ? null
      : draft.input.trim() === ""
        ? "needsInput"
        : expectsSomething(draft)
          ? null
          : "needsExpectation";

  function parsed(): DatasetCaseContent | null {
    try {
      return JSON.parse(json ?? "") as DatasetCaseContent;
    } catch {
      setJsonProblem(true);
      return null;
    }
  }

  function toggleJson() {
    if (json !== null) {
      const content = parsed();
      if (content === null) return;
      setDraft(draftOf({ ...EMPTY_CONTENT, ...content }));
      setJson(null);
      return;
    }
    const read = contentOf(draft);
    if (read.content === null) {
      setErrors(Object.fromEntries(read.problems.map((p) => [p.field, t(p.key)])));
      return;
    }
    setJson(JSON.stringify(read.content, null, 2));
  }

  function edit<K extends keyof CaseDraft>(field: K, value: CaseDraft[K]) {
    if (field === "input") {
      setTwin(null);
      setRepeat(false);
    }
    setDraft((current) => ({ ...current, [field]: value }));
    setErrors(({ [field as CaseField]: _cleared, ...rest }) => rest);
  }

  async function save(
    onSave: (content: DatasetCaseContent) => Promise<unknown>,
    anyway: boolean = repeat,
  ) {
    let content: DatasetCaseContent | null;
    if (json !== null) {
      content = parsed();
    } else {
      const read = contentOf(draft);
      if (read.content === null) {
        setErrors(Object.fromEntries(read.problems.map((p) => [p.field, t(p.key)])));
      }
      content = read.content;
    }
    if (content === null) return;
    setSaving(true);
    try {
      if (twins !== undefined && !anyway) {
        // The check only warns: when it cannot be made, the case is saved as asked.
        const found = await twins.find(content.input).catch(() => null);
        if (found !== null) {
          setTwin({
            found,
            open: () => twins.open(found),
            addAnyway: () => {
              setRepeat(true);
              void save(onSave, true);
            },
          });
          return;
        }
      }
      await onSave(content);
      onOpenChange(false);
    } catch (error) {
      const failure = submitFailure(error, { fields: [...CASE_FIELDS] }, tErrors);
      setErrors(failure.fields);
      if (failure.toast) toast.error(failure.toast);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={cn(DIALOG_COLUMN, DIALOG_WIDE)}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            {onSave === undefined
              ? t("caseReadOnly")
              : !editing
                ? t("caseOpened")
                : nextVersion === undefined
                  ? t("caseSavesVersion")
                  : t("caseSavesVersionN", { number: nextVersion })}
          </DialogDescription>
        </DialogHeader>
        <div className="-mx-1.5 min-h-0 flex-1 space-y-4 overflow-y-auto px-1.5 py-1">
          {!editing && viewing !== undefined && <CaseView content={viewing} />}
          {editing && json !== null && (
            <FormField
              htmlFor="case-json"
              label={t("caseJson")}
              description={t("caseJsonHint")}
              error={jsonProblem ? t("caseJsonInvalid") : undefined}
            >
              <Textarea
                rows={18}
                className="font-mono text-xs"
                value={json}
                onChange={(event) => {
                  setJson(event.target.value);
                  setJsonProblem(false);
                }}
              />
            </FormField>
          )}
          {editing &&
            json === null &&
            GROUPS.map(({ group, slots }) => (
              <div key={group} data-tour={`case-group-${group}`} className="space-y-4">
                {slots.map((slot) => {
                  if (slot === "tags") {
                    return (
                      <FormField
                        key={slot}
                        htmlFor="case-tags"
                        label={t("field.tags")}
                        description={t("hint.tags")}
                        error={errors.tags}
                      >
                        <Input
                          readOnly={readOnly}
                          value={draft.tags}
                          onChange={(event) => edit("tags", event.target.value)}
                        />
                      </FormField>
                    );
                  }
                  if (slot === "history") {
                    return (
                      <ListField key={slot} field={slot} error={errors.history}>
                        <CaseHistoryEditor
                          turns={draft.history}
                          onChange={(history) => edit("history", history)}
                        />
                      </ListField>
                    );
                  }
                  if (slot === "expected_tool_calls") {
                    return (
                      <ListField key={slot} field={slot} error={errors.expected_tool_calls}>
                        <CaseCallsEditor
                          calls={draft.expected_tool_calls}
                          onChange={(calls) => edit("expected_tool_calls", calls)}
                          knownTools={knownTools}
                        />
                      </ListField>
                    );
                  }
                  if (slot === "checks") {
                    return (
                      <ListField key={slot} field={slot} error={errors.checks}>
                        <CaseChecksEditor
                          checks={draft.checks}
                          onChange={(checks) => edit("checks", checks)}
                        />
                      </ListField>
                    );
                  }
                  if (slot === "order_mode") {
                    return (
                      <FormField
                        key={slot}
                        htmlFor="case-order-mode"
                        label={t("field.order_mode")}
                        description={t(`orderMode.${draft.order_mode}Hint`)}
                      >
                        <Select
                          disabled={readOnly}
                          value={draft.order_mode}
                          onValueChange={(next) => edit("order_mode", next as ToolOrderMode)}
                        >
                          <SelectTrigger id="case-order-mode">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {ORDER_MODES.map((mode) => (
                              <SelectItem key={mode} value={mode}>
                                {t(`orderMode.${mode}`)}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </FormField>
                    );
                  }
                  const { field, rows } = slot;
                  return (
                    <FormField
                      key={field}
                      htmlFor={`case-${field}`}
                      label={t(`field.${field}`)}
                      description={t(`hint.${field}`)}
                      error={errors[field]}
                      required={field === "input"}
                    >
                      <Textarea
                        rows={rows}
                        readOnly={readOnly}
                        value={draft[field]}
                        onChange={(event) => edit(field, event.target.value)}
                      />
                    </FormField>
                  );
                })}
              </div>
            ))}
        </div>
        {editing && json === null && scoring !== undefined && (
          <CaseGradedBy scoring={scoring} draft={draft} />
        )}
        {twin !== null && (
          <CaseTwinNotice
            twin={twin.found}
            busy={saving}
            onOpen={twin.open}
            onAddAnyway={twin.addAnyway}
          />
        )}
        <DialogFooter className="items-center">
          {!readOnly && (
            <Button variant="link" size="sm" className="mr-auto px-0" onClick={toggleJson}>
              {json === null ? t("editAsJson") : t("editAsForm")}
            </Button>
          )}
          {!readOnly && missing !== null && (
            <p className="text-muted-foreground text-xs" role="status">
              {t(missing)}
            </p>
          )}
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t(readOnly ? "close" : "cancel")}
          </Button>
          {onSave !== undefined && !editing && (
            <Button data-tour="case-edit" onClick={() => setEditing(true)}>
              {t("editCase")}
            </Button>
          )}
          {!readOnly && (
            <Button
              data-tour="case-save"
              onClick={() => void save(onSave)}
              disabled={saving || missing !== null}
            >
              {t("saveCase")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
