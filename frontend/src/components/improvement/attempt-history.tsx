"use client";

import { useTranslations } from "next-intl";
import type { Improvement } from "@/types/improvement";

/** What each attempt before the current one came to, while the next is under way. */
export function AttemptHistory({ session }: { session: Improvement }) {
  const t = useTranslations("improvement");
  const earlier = session.iterations.filter((round) => round.number < session.iteration);
  if (earlier.length === 0) return null;
  return (
    <ul className="text-muted-foreground space-y-1 text-sm">
      {earlier.map((round) => (
        <li key={round.id}>
          {t("triedAttempt", {
            number: round.number,
            verdict: round.verdict ?? (round.batch_id ? "unmeasured" : "none"),
            dropped: round.dropped.length,
          })}
        </li>
      ))}
    </ul>
  );
}
