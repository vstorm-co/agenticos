"use client";

import { useState } from "react";
import { AlertTriangle } from "lucide-react";

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
 * An empty box is "keep for ever", which is a real answer here and not a missing
 * one: `null` and unset differ on the wire, and this form sends `null`.
 */
export function RetentionForm({ policy, isSaving, saved, onSave }: RetentionFormProps) {
  const t = useTranslations("pages.retention");
  const [draft, setDraft] = useState<Record<string, string>>(() => asText(policy.requested));
  const [shown, setShown] = useState(policy.requested);

  // A save answers with the resolved policy, so the boxes follow what the server
  // stored rather than what was typed at it. Adjusted during render rather than
  // in an effect, which is React's own answer for state derived from a prop: an
  // effect would render the stale boxes once first, and cascade.
  if (shown !== policy.requested) {
    setShown(policy.requested);
    setDraft(asText(policy.requested));
  }

  const submit = async () => {
    const days: RetentionDays = {};
    for (const name of RETENTION_CLASSES) {
      const raw = draft[name]?.trim() ?? "";
      days[name] = raw === "" ? null : Number(raw);
    }
    await onSave(days);
  };

  return (
    <div className="space-y-5">
      {policy.conflicts.length > 0 ? (
        <p className="border-destructive/40 text-destructive flex items-start gap-2 rounded-md border p-3 text-xs">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          {t("conflictingBounds", { classes: policy.conflicts.join(", ") })}
        </p>
      ) : null}

      <div className="overflow-x-auto">
        <table className="w-full min-w-[34rem] text-sm">
          <thead>
            <tr className="border-b">
              <th className="py-2 pr-4 text-left font-medium">{t("dataClass")}</th>
              <th className="px-3 py-2 text-left font-medium">{t("keepForDays")}</th>
              <th className="px-3 py-2 text-left font-medium">{t("whatSweeps")}</th>
            </tr>
          </thead>
          <tbody>
            {RETENTION_CLASSES.map((name) => (
              <tr key={name} className="border-b last:border-0">
                <td className="py-2 pr-4">{t(`classes.${name}`)}</td>
                <td className="px-3 py-2">
                  <Input
                    type="number"
                    min={1}
                    inputMode="numeric"
                    className="h-9 w-28"
                    aria-label={t(`classes.${name}`)}
                    placeholder={t("forEver")}
                    value={draft[name] ?? ""}
                    onChange={(event) =>
                      setDraft((current) => ({ ...current, [name]: event.target.value }))
                    }
                  />
                </td>
                <td className="text-muted-foreground px-3 py-2 text-xs">
                  {describe(policy, name, t)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex items-center gap-3">
        <Button onClick={submit} disabled={isSaving}>
          {isSaving ? t("saving") : t("save")}
        </Button>
        {saved ? <span className="text-muted-foreground text-xs">{t("saved")}</span> : null}
      </div>

      <p className="text-muted-foreground text-xs">{t("hardDeleteNotice")}</p>
    </div>
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
