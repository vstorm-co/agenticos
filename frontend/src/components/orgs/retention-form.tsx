"use client";

import { useId, useRef, useState } from "react";
import { toast } from "sonner";
import { useUnsavedChanges } from "@/hooks/use-unsaved-changes";
import { getErrorMessage } from "@/lib/api-error";
import { AlertTriangle } from "lucide-react";

import {
  RetentionTable,
  RETENTION_ROW,
  RETENTION_NAME,
  RETENTION_INPUT,
  RETENTION_EFFECTIVE,
} from "./retention-table";

import { Button, Input } from "@/components/ui";
import {
  RETENTION_CLASSES,
  type RetentionClass,
  type RetentionDays,
  type RetentionPolicy,
} from "@/lib/retention-api";
import { useTranslations } from "next-intl";

interface RetentionFormProps {
  policy: RetentionPolicy;
  isSaving: boolean;
  saved: boolean;
  onSave: (days: RetentionDays) => Promise<void>;
}

/**
 * One row per class: what was asked for, and what the deployment makes of it.
 *
 * The second column is the reason this is not six inputs. A ceiling cuts a
 * longer period and the audit floor raises a shorter one, so the number that
 * sweeps is frequently not the number in the box beside it - and a page that
 * showed only one of the two would be a page somebody argues with (#1420).
 *
 * An empty box is ambiguous, and the form resolves it by what was typed rather
 * than by what it looks like. Cleared by the person, it means "keep for ever" and
 * sends `null`; never touched, it means this class has no opinion and is left out
 * of the request entirely - because `null` and absent are different answers on
 * the wire, and sending `null` for every empty box made opening the page and
 * saving one row override every deployment default with "for ever".
 */
export function RetentionForm({ policy, isSaving, saved, onSave }: RetentionFormProps) {
  const t = useTranslations("pages.retention");
  const tErrors = useTranslations("errors");
  const form = useRef<HTMLFormElement>(null);
  const guardId = useId();
  const [draft, setDraft] = useState<Record<string, string>>(() => asText(policy.requested));
  const [shown, setShown] = useState(policy.requested);
  // Which rows the person actually touched. An empty box means two different
  // things - "nothing has been said about this class, take the deployment's
  // default" and "keep for ever, deliberately" - and only the typing tells them
  // apart. Sending `null` for every empty box turned opening the page and saving
  // one row into overriding every default with "for ever" (#1420 review).
  const [touched, setTouched] = useState<ReadonlySet<RetentionClass>>(new Set());

  // A save answers with the resolved policy, so the boxes follow what the server
  // stored rather than what was typed at it. An identical background read must
  // not discard a draft. Adjusted during render rather than
  // in an effect, which is React's own answer for state derived from a prop: an
  // effect would render the stale boxes once first, and cascade.
  if (RETENTION_CLASSES.some((name) => shown[name] !== policy.requested[name])) {
    setShown(policy.requested);
    setDraft(asText(policy.requested));
    setTouched(new Set());
  }

  const edit = (name: RetentionClass, value: string) => {
    setDraft((current) => ({ ...current, [name]: value }));
    setTouched((current) => new Set(current).add(name));
  };

  const dirty = [...touched].some((name) => {
    const raw = draft[name]?.trim() ?? "";
    return raw === "" ? policy.requested[name] !== null : Number(raw) !== policy.requested[name];
  });

  const submit = async (): Promise<boolean> => {
    if (isSaving || !dirty || !form.current?.reportValidity()) return false;
    const days: RetentionDays = {};
    for (const name of RETENTION_CLASSES) {
      if (!touched.has(name)) continue;
      const raw = draft[name]?.trim() ?? "";
      days[name] = raw === "" ? null : Number(raw);
    }
    try {
      await onSave(days);
      return true;
    } catch (error) {
      toast.error(getErrorMessage(error, tErrors));
      return false;
    }
  };

  useUnsavedChanges(`org-retention:${guardId}`, {
    dirty,
    save: submit,
    discard: () => {
      setDraft(asText(policy.requested));
      setTouched(new Set());
    },
  });

  return (
    <form
      ref={form}
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
      className="flex min-h-0 flex-1 flex-col"
    >
      {policy.conflicts.length > 0 ? (
        <p className="border-destructive/40 text-destructive m-4 flex items-start gap-2 rounded-md border p-3 text-xs">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          {t("conflictingBounds", { classes: policy.conflicts.join(", ") })}
        </p>
      ) : null}

      <RetentionTable>
        {RETENTION_CLASSES.map((name) => (
          <tr key={name} className={RETENTION_ROW}>
            <th scope="row" className={RETENTION_NAME}>
              {t(`classes.${name}`)}
            </th>
            <td className={RETENTION_INPUT}>
              <label
                className="text-muted-foreground text-xs @3xl/retention:hidden"
                htmlFor={`retention-${guardId}-${name}`}
              >
                {t("keepForDays")}
              </label>
              <Input
                id={`retention-${guardId}-${name}`}
                aria-describedby={`retention-${guardId}-${name}-effective`}
                disabled={isSaving}
                type="number"
                min={1}
                inputMode="numeric"
                className="h-9 w-28"
                aria-label={t(`classes.${name}`)}
                placeholder={t("forEver")}
                value={draft[name] ?? ""}
                onChange={(event) => edit(name, event.target.value)}
              />
            </td>
            <td className={RETENTION_EFFECTIVE} id={`retention-${guardId}-${name}-effective`}>
              <span className="mr-2 font-medium @3xl/retention:hidden">{t("whatSweeps")}</span>
              {describe(policy, name, t)}
            </td>
          </tr>
        ))}
      </RetentionTable>

      <div className="space-y-3 border-t p-4 sm:p-5">
        <div className="flex items-center gap-3">
          <Button type="submit" disabled={isSaving || !dirty}>
            {isSaving ? t("saving") : t("save")}
          </Button>
          {saved && !dirty ? (
            <span role="status" className="text-muted-foreground text-xs">
              {t("saved")}
            </span>
          ) : null}
        </div>

        <p className="text-muted-foreground text-xs">{t("hardDeleteNotice")}</p>
      </div>
    </form>
  );
}

/** The stored periods as the text the inputs hold; for ever is an empty box. */
function asText(requested: RetentionDays): Record<string, string> {
  const text: Record<string, string> = {};
  for (const name of RETENTION_CLASSES) {
    const days = requested[name];
    text[name] = typeof days === "number" ? String(days) : "";
  }
  return text;
}

/** What actually sweeps for this class, and why it is not what was asked. */
function describe(
  policy: RetentionPolicy,
  name: RetentionClass,
  t: (key: string, values?: Record<string, string | number>) => string,
): string {
  const effective = policy.effective[name];
  if (effective === null || effective === undefined) return t("keptForEver");
  if (name === "audit") return t("atLeastDays", { days: effective });
  const ceiling = policy.ceilings[name];
  if (typeof ceiling === "number" && ceiling === effective) {
    return t("cappedByDeployment", { days: effective });
  }
  return t("afterDays", { days: effective });
}
