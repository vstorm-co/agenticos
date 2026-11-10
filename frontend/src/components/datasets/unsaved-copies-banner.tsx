"use client";

import { useLocale, useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { JsonView } from "@/components/ui/json-view";
import type { UnsavedCopy } from "@/lib/unsaved-copies";
import { timeAgo } from "@/lib/utils";
import type { CaseCopy } from "./case-editor-dialog";
import { contentOf } from "./case-form";
import { CaseView } from "./case-view";

const QUESTION_LENGTH = 80;

function placeOf(copy: UnsavedCopy): "grading" | "newCase" | "case" {
  if (copy.place === "grading") return "grading";
  return copy.place === "case:new" ? "newCase" : "case";
}

/** The kept change as it would read, for one the dataset has moved past. */
function Changes({ copy }: { copy: UnsavedCopy }) {
  if (placeOf(copy) === "grading") return <JsonView value={copy.value} />;
  const { draft, json } = copy.value as CaseCopy;
  if (json !== null) return <pre className="text-xs whitespace-pre-wrap">{json}</pre>;
  const read = contentOf(draft);
  return read.content === null ? <JsonView value={draft} /> : <CaseView content={read.content} />;
}

function CopyRow({
  copy,
  latest,
  onRestore,
  onDiscard,
}: {
  copy: UnsavedCopy;
  latest: number;
  onRestore: () => void;
  onDiscard: () => void;
}) {
  const t = useTranslations("unsaved");
  const tTime = useTranslations("time");
  const locale = useLocale();
  const place = placeOf(copy);
  const question = place === "grading" ? "" : (copy.value as CaseCopy).draft.input.trim();
  const current = copy.base === latest;
  return (
    <li className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <p className="min-w-0 flex-1 text-sm">
          {t("copy", {
            place,
            question:
              question.length > QUESTION_LENGTH
                ? `${question.slice(0, QUESTION_LENGTH)}…`
                : question,
            when: timeAgo(copy.savedAt, tTime, locale),
          })}
        </p>
        {current && (
          <Button size="sm" onClick={onRestore}>
            {t("restore")}
          </Button>
        )}
        <Button size="sm" variant="outline" onClick={onDiscard}>
          {t("discard")}
        </Button>
      </div>
      {!current && (
        <>
          <p className="text-muted-foreground text-xs">
            {t("movedOn", { base: copy.base, latest })}
          </p>
          <details>
            <summary className="cursor-pointer text-xs underline underline-offset-4">
              {t("showChanges")}
            </summary>
            <div className="mt-2">
              <Changes copy={copy} />
            </div>
          </details>
        </>
      )}
    </li>
  );
}

/**
 * Changes somebody left this dataset without saving, kept in their browser:
 * each can be brought back while the dataset is still at the version it was
 * made on, and discarded either way.
 */
export function UnsavedCopiesBanner({
  copies,
  latest,
  onRestore,
  onDiscard,
}: {
  copies: UnsavedCopy[];
  latest: number;
  onRestore: (copy: UnsavedCopy) => void;
  onDiscard: (copy: UnsavedCopy) => void;
}) {
  const t = useTranslations("unsaved");
  return (
    <section
      aria-label={t("restoreTitle")}
      className="bg-warning/10 border-warning/35 space-y-3 rounded-xl border p-4"
    >
      <div>
        <p className="font-semibold">{t("restoreTitle")}</p>
        <p className="text-muted-foreground text-sm">{t("restoreBody")}</p>
      </div>
      <ul className="space-y-3">
        {copies.map((copy) => (
          <CopyRow
            key={copy.key}
            copy={copy}
            latest={latest}
            onRestore={() => onRestore(copy)}
            onDiscard={() => onDiscard(copy)}
          />
        ))}
      </ul>
    </section>
  );
}
