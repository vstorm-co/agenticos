"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { MarkdownContent } from "@/components/chat/markdown-content";
import { Button } from "@/components/ui";
import { cn } from "@/lib/utils";

/** Past this many characters the answer opens folded, to three lines. */
const FOLDED_PAST = 240;

/**
 * What the run answered, folded when long; `null` once nothing of it is kept, or
 * `hidden` from a reader who may not view the agent that gave it.
 */
export function ScoreAnswer({
  answer,
  hidden = false,
}: {
  answer: string | null;
  hidden?: boolean;
}) {
  const t = useTranslations("datasets.scoring");
  const long = answer !== null && answer.length > FOLDED_PAST;
  const [open, setOpen] = useState(false);

  return (
    <section className="space-y-3 rounded-lg border p-4">
      <h3 className="text-sm font-medium">{t("answer")}</h3>
      {hidden ? (
        <p className="text-muted-foreground text-sm italic">{t("answerHidden")}</p>
      ) : answer === null ? (
        <p className="text-muted-foreground text-sm italic">{t("answerGone")}</p>
      ) : (
        <>
          <div
            className={cn(
              "prose-sm min-w-0 text-sm leading-relaxed wrap-anywhere",
              long && !open && "line-clamp-3",
            )}
          >
            <MarkdownContent content={answer} inertImages />
          </div>
          {long && (
            <Button
              variant="link"
              size="sm"
              className="h-auto px-0"
              aria-expanded={open}
              onClick={() => setOpen((current) => !current)}
            >
              {open ? t("showLess") : t("showAll")}
            </Button>
          )}
        </>
      )}
    </section>
  );
}
