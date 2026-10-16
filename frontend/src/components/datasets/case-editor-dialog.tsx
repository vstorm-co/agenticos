"use client";

import { useState } from "react";
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
import type { DatasetCaseContent, ToolOrderMode } from "@/types/datasets";
import {
  CASE_FIELDS,
  contentOf,
  expectsSomething,
  type CaseDraft,
  type CaseField,
} from "./case-form";

interface CaseEditorDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The fields to start from: blank for a new case, the case's own for an edit. */
  initial: CaseDraft;
  /** Absent for a case that is only read - an older version, or no edit access. */
  onSave?: (content: DatasetCaseContent) => Promise<unknown>;
  title: string;
}

const ORDER_MODES: ToolOrderMode[] = ["any", "in_order", "exact"];

/** A JSON field's shape, shown in the empty box. Code, not copy: it is what is typed. */
const JSON_EXAMPLE: Partial<Record<CaseField, string>> = {
  history: '[{"role": "user", "content": "..."}]',
  expected_tool_calls: '[{"tool": "search", "args": {"q": "refund"}}]',
  checks: '[{"type": "contains", "value": "30 days"}]',
};

type Slot = { field: CaseField; rows: number } | "tags" | "order_mode";

/**
 * The fields in the groups a person thinks in, each a `data-tour` the guided
 * creation stops on: what is asked, what a good and a bad answer are, the tools,
 * the checks, and the labels.
 */
const GROUPS: { group: string; slots: Slot[] }[] = [
  {
    group: "question",
    slots: [
      { field: "input", rows: 3 },
      { field: "history", rows: 4 },
    ],
  },
  {
    group: "answers",
    slots: [
      { field: "reference_answer", rows: 3 },
      { field: "counter_example", rows: 3 },
    ],
  },
  { group: "tools", slots: [{ field: "expected_tool_calls", rows: 4 }, "order_mode"] },
  { group: "checks", slots: [{ field: "checks", rows: 4 }] },
  { group: "labels", slots: ["tags", { field: "note", rows: 2 }] },
];

/**
 * One case, written or read.
 *
 * Saving an edit is a new version of the dataset, and the dialog says so: the
 * case a past eval run answered is still there in the version it ran against.
 */
export function CaseEditorDialog({
  open,
  onOpenChange,
  initial,
  onSave,
  title,
}: CaseEditorDialogProps) {
  const t = useTranslations("datasets");
  const tErrors = useTranslations("errors");
  const [draft, setDraft] = useState(initial);
  const [errors, setErrors] = useState<Partial<Record<CaseField, string>>>({});
  const [saving, setSaving] = useState(false);
  const readOnly = onSave === undefined;
  const missing =
    draft.input.trim() === "" ? "needsInput" : expectsSomething(draft) ? null : "needsExpectation";

  function edit<K extends keyof CaseDraft>(field: K, value: CaseDraft[K]) {
    setDraft((current) => ({ ...current, [field]: value }));
    setErrors(({ [field as CaseField]: _cleared, ...rest }) => rest);
  }

  async function save(onSave: (content: DatasetCaseContent) => Promise<unknown>) {
    const read = contentOf(draft);
    if (read.content === null) {
      setErrors(Object.fromEntries(read.problems.map((p) => [p.field, t(p.key)])));
      return;
    }
    setSaving(true);
    try {
      await onSave(read.content);
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
          <DialogDescription>{t(readOnly ? "caseReadOnly" : "caseSavesVersion")}</DialogDescription>
        </DialogHeader>
        <div className="-mx-1.5 min-h-0 flex-1 space-y-4 overflow-y-auto px-1.5 py-1">
          {GROUPS.map(({ group, slots }) => (
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
                      className={cn(JSON_EXAMPLE[field] !== undefined && "font-mono text-xs")}
                      placeholder={JSON_EXAMPLE[field]}
                      value={draft[field] as string}
                      onChange={(event) => edit(field, event.target.value)}
                    />
                  </FormField>
                );
              })}
            </div>
          ))}
        </div>
        <DialogFooter className="items-center">
          {!readOnly && missing !== null && (
            <p className="text-muted-foreground mr-auto text-xs" role="status">
              {t(missing)}
            </p>
          )}
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t(readOnly ? "close" : "cancel")}
          </Button>
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
