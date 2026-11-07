"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { Button, Label, Textarea } from "@/components/ui";
import type { StartGoal } from "@/lib/onboarding-api";

/** A static preview is explicitly labelled and never records real task success. */
export function StartExample({
  goal,
  onRun,
  onBack,
}: {
  goal: StartGoal;
  onRun?: (prompt: string) => void;
  onBack?: () => void;
}) {
  const t = useTranslations("start");
  const [prompt, setPrompt] = useState(t(`examples.${goal}.prompt`));
  return (
    <section className="mx-auto w-full max-w-2xl space-y-4 p-6">
      <h2 className="text-xl font-semibold">{t(`examples.${goal}.title`)}</h2>
      <p className="text-muted-foreground text-sm">{t(onRun ? "exampleHint" : "demoHint")}</p>
      <Label htmlFor="start-material">{t("material")}</Label>
      <Textarea
        id="start-material"
        value={prompt}
        onChange={(event) => setPrompt(event.target.value)}
        readOnly={!onRun}
        rows={8}
      />
      {onRun ? (
        <>
          <p className="text-muted-foreground text-xs">{t("runNotice")}</p>
          <Button onClick={() => onRun(prompt)} disabled={!prompt.trim()}>
            {t("run")}
          </Button>
        </>
      ) : (
        <div className="bg-muted rounded-xl p-4" role="note">
          <h3 className="mb-2 font-medium">{t("recordedExample")}</h3>
          <p className="text-sm whitespace-pre-line">{t(`examples.${goal}.result`)}</p>
          <p className="text-muted-foreground mt-3 text-xs">{t("demoNotRun")}</p>
        </div>
      )}
      <p>
        {onBack ? (
          <Button variant="ghost" onClick={onBack}>
            {t("back")}
          </Button>
        ) : (
          <Link href="/onboarding" className="text-sm underline underline-offset-4">
            {t("back")}
          </Link>
        )}
      </p>
    </section>
  );
}
