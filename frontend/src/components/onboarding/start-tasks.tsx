"use client";

import { useState } from "react";
import {
  ArrowRight,
  Bot,
  CheckCircle2,
  CircleCheck,
  CircleHelp,
  Mail,
  RotateCw,
  ShieldCheck,
} from "lucide-react";
import { StartTaskArtwork } from "./start-task-artwork";
import styles from "./start.module.css";
import { useTranslations } from "next-intl";
import {
  Button,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useStart } from "@/hooks/use-start";
import { useRouter } from "@/lib/locale-navigation";
import { START_GOALS, exampleChat, type Onboarding, type StartGoal } from "@/lib/onboarding-api";
import { getErrorMessage } from "@/lib/api-error";
import { StartExample } from "./start-example";
import { StartModel } from "./start-model";

export function StartTasks({ data }: { data: Onboarding }) {
  const t = useTranslations("start");
  const errors = useTranslations("errors");
  const state = useStart();
  const router = useRouter();
  const [selected, setSelected] = useState<string | null>(null);
  const [demo, setDemo] = useState<StartGoal | null>(null);
  const agent = data.agents.find((item) => item.id === selected) ?? data.agents[0];
  const choose = async (goal: StartGoal) => {
    await state.save.mutateAsync({ goal });
    if (agent) router.push(exampleChat(agent.id, goal));
    else setDemo(goal);
  };
  return (
    <div className={styles.tasks}>
      <div className={styles.readiness}>
        <p className={styles.status} role="status">
          {agent ? <CircleCheck size={16} aria-hidden /> : <CircleHelp size={16} aria-hidden />}
          {t(agent ? "ready" : "notReady")}
        </p>
        {agent && data.agents.length === 1 && (
          <p className={styles.agent}>
            <Bot size={15} aria-hidden />
            {t("agent")}: <strong>{agent.name}</strong>
          </p>
        )}
        {data.agents.length > 1 && (
          <div className="max-w-sm space-y-2">
            <Label htmlFor="start-agent">{t("agent")}</Label>
            <Select value={agent?.id} onValueChange={setSelected}>
              <SelectTrigger id="start-agent">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {data.agents.map((item) => (
                  <SelectItem key={item.id} value={item.id}>
                    {item.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}
      </div>
      <section aria-label={t("examplesTitle")}>
        <ul className={styles.grid}>
          {START_GOALS.map((goal) => (
            <li key={goal} className={styles.card} data-selected={data.goal === goal}>
              {data.goal === goal && (
                <CheckCircle2 size={18} className={styles.selected} aria-hidden />
              )}
              <StartTaskArtwork goal={goal} />
              <div className={styles.cardBody}>
                <h2 className={styles.cardTitle}>{t(`examples.${goal}.title`)}</h2>
                <p className={styles.cardDescription}>{t(`examples.${goal}.description`)}</p>
                <Button
                  className={styles.cardAction}
                  variant={
                    data.goal === goal || (!data.goal && goal === "meeting") ? "default" : "outline"
                  }
                  disabled={state.save.isPending}
                  onClick={() => {
                    void choose(goal).catch(() => {
                      /* The mutation error stays visible below the choices. */
                    });
                  }}
                >
                  {t(agent ? "tryExample" : "showExample")}
                  <ArrowRight size={15} aria-hidden />
                </Button>
              </div>
            </li>
          ))}
        </ul>
      </section>
      {state.save.error && (
        <p role="alert" className="text-destructive text-sm">
          {getErrorMessage(state.save.error, errors)}
        </p>
      )}
      {demo && <StartExample key={demo} goal={demo} onBack={() => setDemo(null)} />}
      {!agent &&
        (data.can_prepare ? (
          <StartModel allowAdd={data.can_configure_model} />
        ) : (
          <section className={`${styles.panel} space-y-3`}>
            <h2 className={`${styles.panelHeading} font-semibold`}>
              <CircleHelp size={18} aria-hidden />
              {t("askOwner")}
            </h2>
            <p className="text-muted-foreground text-sm">{t("askOwnerHint")}</p>
            {data.support_email && (
              <a className="mr-3 text-sm underline" href={`mailto:${data.support_email}`}>
                <Mail size={14} className="mr-1.5 inline" aria-hidden />
                {data.support_email}
              </a>
            )}
            <Button variant="outline" onClick={() => void state.refetch()}>
              <RotateCw size={14} aria-hidden />
              {t("checkAgain")}
            </Button>
          </section>
        ))}
      {agent && data.can_prepare && (
        <details className="rounded-xl border px-5 py-4">
          <summary className="cursor-pointer text-sm">{t("connectTitle")}</summary>
          <div className="mt-4">
            <StartModel allowAdd={data.can_configure_model} />
          </div>
        </details>
      )}
      {agent && (
        <p className={styles.note}>
          <ShieldCheck size={14} aria-hidden />
          {t("runNotice")}
        </p>
      )}
    </div>
  );
}
