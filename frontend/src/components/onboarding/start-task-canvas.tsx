"use client";

import { useTranslations } from "next-intl";
import { Bot, FileText, Eye } from "lucide-react";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui";
import type { StartGoal } from "@/lib/onboarding-api";
import { StartTaskResult } from "./start-task-result";
import styles from "./workbench.module.css";

export function StartTaskCanvas({ goal }: { goal: StartGoal }) {
  const t = useTranslations("start");
  return (
    <>
      <header className={styles.canvasHeader}>
        <p className={styles.demoLabel}>
          <Eye size={14} aria-hidden />
          {t("workbench.demoLabel")}
        </p>
        <h2>{t(`examples.${goal}.title`)}</h2>
      </header>
      <Tabs defaultValue="result" className={styles.document}>
        <TabsList aria-label={t("workbench.views")} className={styles.documentTabs}>
          <TabsTrigger value="result">
            <Bot size={15} aria-hidden />
            {t("workbench.result")}
          </TabsTrigger>
          <TabsTrigger value="material">
            <FileText size={15} aria-hidden />
            {t("workbench.source")}
          </TabsTrigger>
        </TabsList>
        <TabsContent value="result" className={styles.documentBody}>
          <StartTaskResult goal={goal} />
        </TabsContent>
        <TabsContent value="material" className={styles.documentBody}>
          <p className={styles.source}>{t(`examples.${goal}.prompt`)}</p>
        </TabsContent>
      </Tabs>
      <p role="note" className={styles.demoNotice}>
        {t("workbench.demoNotice")}
      </p>
    </>
  );
}
