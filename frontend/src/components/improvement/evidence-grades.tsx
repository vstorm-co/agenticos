"use client";

import { useLocale, useTranslations } from "next-intl";
import type { EvidenceGrade, ImprovementEvidenceItem } from "@/types/improvement";

/** A judge's reason opens on the grade it gave, `3/5: ...`. */
const JUDGED = /^(\d+\/\d+): ([\s\S]*)$/;

function judged(grade: EvidenceGrade) {
  const match = grade.scorer === "judge" ? JUDGED.exec(grade.reason) : null;
  return match ? { score: match[1]!, reason: match[2]! } : null;
}

/** How a test question's answer was graded, one sentence per check and criterion. */
export function Grades({ items }: { items: ImprovementEvidenceItem[] }) {
  const t = useTranslations("improvement.grading");
  const grades = items.flatMap((item) => item.grades ?? []);
  if (!grades.length) return null;
  return (
    <div>
      <h4 className="text-xs font-medium">{t("heading")}</h4>
      <ul className="text-muted-foreground mt-1 space-y-1 break-words">
        {grades.map((grade, index) => {
          const scored = judged(grade);
          return (
            <li key={index}>
              {grade.scorer !== "judge"
                ? t("rule", { name: grade.name, status: grade.status })
                : scored
                  ? t("judge", { name: grade.name, ...scored })
                  : t("judgeSaid", { name: grade.name, reason: grade.reason })}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/**
 * Why an example counts as a problem, from what it holds: the grades its test answer
 * failed, how a person rated it, and what the classifier said.
 */
export function WhyCause({ items }: { items: ImprovementEvidenceItem[] }) {
  const t = useTranslations("improvement");
  const locale = useLocale();
  const failed = items.flatMap((item) => (item.grades ?? []).filter((g) => g.status === "fail"));
  const chat = items.find((item) => item.kind === "chat");
  const lines: string[] = [];
  if (failed.length) {
    const names = failed.map((grade) =>
      t("why.grade", { name: grade.name, score: judged(grade)?.score ?? "none" }),
    );
    lines.push(
      t("why.failed", {
        grades: new Intl.ListFormat(locale, { type: "conjunction" }).format(names),
      }),
    );
  }
  if (chat && chat.status !== "completed") lines.push(t("why.runFailed"));
  else if (chat && chat.rating < 0)
    lines.push(
      t("why.ratedDown", {
        commented: chat.comments.length ? "yes" : "no",
        comment: chat.comments[0] ?? "",
      }),
    );
  else if (chat && chat.rating > 0) lines.push(t("why.ratedUp"));
  const reason = items.find((item) => item.reason)?.reason;
  if (reason) lines.push(reason);
  else if (items.some((item) => item.branch === "unknown")) lines.push(t("causeUnknown"));
  if (!lines.length)
    lines.push(
      t(items.some((item) => item.kind === "train_eval") ? "causeTraining" : "causeRecorded"),
    );
  return (
    <div>
      <h4 className="text-xs font-medium">{t("whyCause")}</h4>
      {lines.map((line, index) => (
        <p key={index} className="text-muted-foreground mt-1 break-words">
          {line}
        </p>
      ))}
    </div>
  );
}
