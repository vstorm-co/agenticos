"use client";

import { useId, useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import {
  CheckCheck,
  ChevronRight,
  Code2,
  GitCompareArrows,
  History,
  ListChecks,
  MessageSquare,
  Pencil,
  Save,
  Tags,
  ThumbsDown,
  Wrench,
  type LucideIcon,
} from "lucide-react";

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
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetClose,
  Textarea,
} from "@/components/ui";
import { useUnsavedChanges } from "@/hooks/use-unsaved-changes";
import { submitFailure } from "@/lib/api-error";
import { DIALOG_BODY, DIALOG_BROAD, DIALOG_COLUMN } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import { useUnsavedChangesStore } from "@/stores/unsaved-changes-store";
import type { DatasetCase, DatasetCaseContent, ToolOrderMode } from "@/types/datasets";
import type { DatasetScoring } from "@/types/scoring";
import { DatasetChip } from "./dataset-chip";
import { CaseCallsEditor } from "./case-calls-editor";
import { CaseChecksEditor } from "./case-checks-editor";
import { CaseGradedBy } from "./case-graded-by";
import { CaseTwinNotice } from "./case-twin-notice";
import {
  CASE_FIELDS,
  caseContentFromJson,
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
  /** What saving does, when it is not "a new version of the dataset". */
  description?: string;
  /** The save button, when it is not "Save case". */
  saveLabel?: string;
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
  /** An unsaved edit to pick up from, in place of `initial`, which stays what it changes. */
  startFrom?: CaseCopy;
  /** Where an unsaved edit is kept in this browser, and the version it is made on. */
  localCopy?: { key: string; base: number };
}

/** What a kept copy of an unsaved case edit holds. */
export interface CaseCopy {
  draft: CaseDraft;
  json: string | null;
}

const GROUP_ICONS: Record<string, LucideIcon> = {
  history: History,
  counter: ThumbsDown,
  tools: Wrench,
  checks: ListChecks,
  labels: Tags,
};

const ORDER_MODES: ToolOrderMode[] = ["any", "in_order", "exact"];

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
    slots: [{ field: "input", rows: 6 }],
  },
  {
    group: "answers",
    slots: [{ field: "reference_answer", rows: 6 }],
  },
  { group: "history", slots: ["history"] },
  { group: "counter", slots: [{ field: "counter_example", rows: 3 }] },
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
      {error && <p className="text-destructive-ink text-xs">{error}</p>}
    </fieldset>
  );
}

function CaseGroup({
  group,
  children,
  expanded,
}: {
  group: string;
  children: ReactNode;
  expanded: boolean;
}) {
  const t = useTranslations("datasets");
  const Icon = GROUP_ICONS[group];
  if (group === "question" || group === "answers")
    return (
      <section data-tour={`case-group-${group}`} className="min-w-0 space-y-4">
        {children}
      </section>
    );
  return (
    <details
      data-tour={`case-group-${group}`}
      open={expanded || undefined}
      className="group min-w-0 border-t"
    >
      <summary className="text-muted-foreground hover:text-foreground flex cursor-pointer list-none items-center gap-2 py-3 text-sm font-medium [&::-webkit-details-marker]:hidden">
        <ChevronRight
          aria-hidden
          className="size-4 shrink-0 transition-transform group-open:rotate-90"
        />
        {Icon && <Icon className="size-4" aria-hidden />}
        {t(`caseSection.${group}`)}
      </summary>
      <div className="space-y-4 pb-4">{children}</div>
    </details>
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
  description,
  saveLabel,
  nextVersion,
  scoring,
  knownTools,
  twins,
  startFrom,
  localCopy,
}: CaseEditorDialogProps) {
  const t = useTranslations("datasets");
  const tErrors = useTranslations("errors");
  const [draft, setDraft] = useState(startFrom?.draft ?? initial);
  const [errors, setErrors] = useState<Partial<Record<CaseField, string>>>({});
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState(viewing === undefined || startFrom !== undefined);
  const [json, setJson] = useState<string | null>(startFrom?.json ?? null);
  const [jsonProblem, setJsonProblem] = useState(false);
  const [twin, setTwin] = useState<{
    found: DatasetCase;
    open: () => void;
    addAnyway: () => void;
  } | null>(null);
  const [repeat, setRepeat] = useState(false);
  const readOnly = onSave === undefined || !editing;
  const changed = !readOnly && (json !== null || JSON.stringify(draft) !== JSON.stringify(initial));
  const missing =
    json !== null
      ? null
      : draft.input.trim() === ""
        ? "needsInput"
        : expectsSomething(draft)
          ? null
          : "needsExpectation";
  const source = useId();
  const { forget } = useUnsavedChanges(source, {
    dirty: changed,
    // Only a case that would save as it stands can be saved on the way out.
    save: onSave === undefined || missing !== null ? undefined : () => save(onSave),
    discard: () => onOpenChange(false),
    copy: localCopy && { ...localCopy, value: { draft, json } satisfies CaseCopy },
  });
  // Escape, a click outside and Cancel all close the dialog; with a change not
  // yet saved, each asks first.
  const close = () => {
    if (!saving) useUnsavedChangesStore.getState().leave(() => onOpenChange(false), [source]);
  };

  function parsed(): DatasetCaseContent | null {
    try {
      const decoded: unknown = JSON.parse(json ?? "");
      const content = caseContentFromJson(decoded);
      if (content === null) setJsonProblem(true);
      return content;
    } catch {
      setJsonProblem(true);
      return null;
    }
  }

  function toggleJson() {
    if (json !== null) {
      const content = parsed();
      if (content === null) return;
      setDraft(draftOf(content));
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

  /** Saves the case; true once it is saved, false when it is refused or waits on a twin. */
  async function save(
    onSave: (content: DatasetCaseContent) => Promise<unknown>,
    anyway: boolean = repeat,
  ): Promise<boolean> {
    if (saving) return false;
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
    if (content === null) return false;
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
          return false;
        }
      }
      await onSave(content);
      forget();
      onOpenChange(false);
      return true;
    } catch (error) {
      const failure = submitFailure(error, { fields: [...CASE_FIELDS] }, tErrors);
      setErrors(failure.fields);
      if (failure.toast) toast.error(failure.toast);
      return false;
    } finally {
      setSaving(false);
    }
  }

  if (!editing && viewing !== undefined) {
    return (
      <Sheet
        open={open}
        onOpenChange={(next) => {
          if (!next) close();
        }}
      >
        <SheetContent side="right" className="bg-background w-full sm:max-w-3xl">
          <SheetHeader className="shrink-0 py-4">
            <div className="min-w-0">
              <SheetTitle className="break-words">{title}</SheetTitle>
              {onSave === undefined && (
                <p className="text-muted-foreground text-xs">{t("caseReadOnly")}</p>
              )}
            </div>
            <div className="flex shrink-0 items-center gap-2">
              {onSave !== undefined && (
                <Button
                  size="sm"
                  variant="outline"
                  data-tour="case-edit"
                  onClick={() => setEditing(true)}
                >
                  <Pencil className="size-3.5" />
                  {t("editCase")}
                </Button>
              )}
              <SheetClose onClick={close} />
            </div>
          </SheetHeader>
          <div className="min-h-0 flex-1 overflow-y-auto">
            <div className="mx-auto w-full max-w-2xl px-4 py-6 sm:px-8 sm:py-8">
              <CaseView content={viewing} />
            </div>
          </div>
        </SheetContent>
      </Sheet>
    );
  }
  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent
        dismissible={!saving}
        className={cn(DIALOG_BROAD, DIALOG_COLUMN, "max-sm:h-[var(--dialog-available-height)]")}
      >
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            {description ??
              (onSave === undefined
                ? t("caseReadOnly")
                : nextVersion === undefined
                  ? t("caseSavesVersion")
                  : t("caseSavesVersionN", { number: nextVersion }))}
          </DialogDescription>
        </DialogHeader>
        <div className={DIALOG_BODY}>
          <fieldset disabled={saving} className="min-w-0">
            <legend className="sr-only">{title}</legend>
            {editing && json !== null && (
              <FormField
                htmlFor="case-json"
                label={t("caseJson")}
                description={t("caseJsonHint")}
                error={jsonProblem ? t("caseJsonInvalid") : undefined}
              >
                <Textarea
                  rows={18}
                  className="font-mono text-base md:text-xs"
                  value={json}
                  onChange={(event) => {
                    setJson(event.target.value);
                    setJsonProblem(false);
                  }}
                />
              </FormField>
            )}
            {editing && json === null && (
              <div className="grid items-start gap-5 lg:grid-cols-2">
                {[
                  {
                    title: "conversation",
                    groups: GROUPS.filter(({ group }) =>
                      ["question", "history", "labels"].includes(group),
                    ),
                  },
                  {
                    title: "expectations",
                    groups: GROUPS.filter(({ group }) =>
                      ["answers", "counter", "tools", "checks"].includes(group),
                    ),
                  },
                ].map(({ title: column, groups }) => (
                  <section
                    key={column}
                    aria-label={t(`editor.${column}`)}
                    className="bg-background/40 min-w-0 rounded-xl border"
                  >
                    <header className="border-b px-4 py-3">
                      <h3 className="flex items-center gap-2 text-sm font-semibold">
                        <DatasetChip
                          tone={column === "conversation" ? "blue" : "green"}
                          icon={column === "conversation" ? MessageSquare : CheckCheck}
                        >
                          {t(`editor.${column}`)}
                        </DatasetChip>
                      </h3>
                      <p className="text-muted-foreground mt-1 text-xs leading-relaxed">
                        {t(`editor.${column}Hint`)}
                      </p>
                    </header>
                    <div className="space-y-4 p-4">
                      {groups.map(({ group, slots }) => (
                        <CaseGroup
                          key={group}
                          group={group}
                          expanded={
                            group === "history"
                              ? draft.history.length > 0 || errors.history !== undefined
                              : group === "counter"
                                ? draft.counter_example.length > 0 ||
                                  errors.counter_example !== undefined
                                : group === "tools"
                                  ? draft.expected_tool_calls.length > 0 ||
                                    errors.expected_tool_calls !== undefined
                                  : group === "checks"
                                    ? draft.checks.length > 0 || errors.checks !== undefined
                                    : group === "labels"
                                      ? draft.tags.length > 0 ||
                                        draft.note.length > 0 ||
                                        errors.tags !== undefined ||
                                        errors.note !== undefined
                                      : false
                          }
                        >
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
                                    placeholder={t("tagsPlaceholder")}
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
                                <ListField
                                  key={slot}
                                  field={slot}
                                  error={errors.expected_tool_calls}
                                >
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
                                    onValueChange={(next) =>
                                      edit("order_mode", next as ToolOrderMode)
                                    }
                                  >
                                    <SelectTrigger id="case-order-mode">
                                      <SelectValue />
                                    </SelectTrigger>
                                    <SelectContent>
                                      {ORDER_MODES.map((mode) => (
                                        <SelectItem
                                          key={mode}
                                          value={mode}
                                          textValue={t(`orderMode.${mode}`)}
                                        >
                                          <DatasetChip
                                            tone={
                                              mode === "any"
                                                ? "blue"
                                                : mode === "in_order"
                                                  ? "purple"
                                                  : "yellow"
                                            }
                                            icon={GitCompareArrows}
                                          >
                                            {t(`orderMode.${mode}`)}
                                          </DatasetChip>
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
                                label={
                                  <span className="inline-flex flex-wrap items-center gap-2">
                                    {t(`field.${field}`)}
                                    {field !== "input" && (
                                      <span
                                        aria-hidden
                                        className="text-muted-foreground text-xs font-normal"
                                      >
                                        {t("optionalField")}
                                      </span>
                                    )}
                                  </span>
                                }
                                description={t(`hint.${field}`)}
                                error={errors[field]}
                                required={field === "input"}
                              >
                                <Textarea
                                  rows={rows}
                                  className={
                                    field === "input" || field === "reference_answer"
                                      ? "max-sm:h-28"
                                      : undefined
                                  }
                                  placeholder={t(`placeholder.${field}`)}
                                  aria-label={t(`field.${field}`)}
                                  readOnly={readOnly}
                                  value={draft[field]}
                                  onChange={(event) => edit(field, event.target.value)}
                                />
                              </FormField>
                            );
                          })}
                        </CaseGroup>
                      ))}
                    </div>
                  </section>
                ))}
              </div>
            )}
            {editing &&
              json === null &&
              scoring !== undefined &&
              draft.input.trim() !== "" &&
              expectsSomething(draft) && (
                <div className="mt-4">
                  <CaseGradedBy scoring={scoring} draft={draft} />
                </div>
              )}
            {twin !== null && (
              <CaseTwinNotice
                twin={twin.found}
                busy={saving}
                onOpen={twin.open}
                onAddAnyway={twin.addAnyway}
              />
            )}
          </fieldset>
        </div>
        <DialogFooter className="items-center border-t">
          {!readOnly && (
            <Button
              variant="link"
              size="sm"
              className="mr-auto px-0"
              onClick={toggleJson}
              disabled={saving}
            >
              <Code2 className="size-4" aria-hidden />
              {json === null ? t("editAsJson") : t("editAsForm")}
            </Button>
          )}
          {!readOnly && missing !== null && (
            <p className="text-muted-foreground text-xs" role="status">
              {t(missing)}
            </p>
          )}
          <Button variant="outline" onClick={close} disabled={saving}>
            {t(readOnly ? "close" : "cancel")}
          </Button>
          {!readOnly && (
            <Button
              data-tour="case-save"
              loading={saving}
              onClick={() => void save(onSave)}
              disabled={saving || missing !== null}
            >
              <Save className="size-4" aria-hidden />
              {saveLabel ?? t("saveCase")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
