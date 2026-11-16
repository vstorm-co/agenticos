"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { ArrowLeft, FileText, NotebookPen, Columns3, Play, ShieldCheck } from "lucide-react";
import styles from "./start.module.css";
import { Button, Label, Textarea } from "@/components/ui";
import type { StartGoal } from "@/lib/onboarding-api";

/** A static preview is explicitly labelled and never records real task success. */
export function StartExample({
  goal,
  onRun,
}: {
  goal: StartGoal;
  onRun?: (prompt: string) => void;
}) {
  const t = useTranslations("start");
  const [prompt, setPrompt] = useState(t(`examples.${goal}.prompt`));
  const Icon = { meeting: NotebookPen, document: FileText, compare: Columns3 }[goal];
  return (
    <section className={`${styles.example} ${styles.enter} space-y-5`}>
      <div className={styles.exampleHeader}>
        <Icon size={26} className="mt-1 shrink-0" aria-hidden />
        <h2 className="text-xl font-semibold tracking-tight focus:outline-none">
          {t(`examples.${goal}.title`)}
        </h2>
      </div>
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
          <p className={styles.note}>
            <ShieldCheck size={14} aria-hidden />
            {t("runNotice")}
          </p>
          <Button
            className="rounded-lg px-6"
            onClick={() => onRun(prompt)}
            disabled={!prompt.trim()}
          >
            <Play size={15} aria-hidden />
            {t("run")}
          </Button>
        </>
      ) : (
        <div className={styles.exampleResult} role="note">
          <h3 className="mb-3 flex items-center gap-2 font-medium">
            <FileText size={16} aria-hidden />
            {t("recordedExample")}
          </h3>
          <p className="text-sm whitespace-pre-line">{t(`examples.${goal}.result`)}</p>
          <p className="text-muted-foreground mt-3 text-xs">{t("demoNotRun")}</p>
        </div>
      )}
      <p>
        <Link href="/onboarding" className="text-sm underline underline-offset-4">
          <ArrowLeft size={14} className="mr-1.5 inline" aria-hidden />
          {t("back")}
        </Link>
      </p>
    </section>
  );
}
