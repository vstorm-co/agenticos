"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowRight, LoaderCircle } from "lucide-react";
import { useTranslations } from "next-intl";
import { Button, Label } from "@/components/ui";
import { useStart } from "@/hooks/use-start";
import { useRouter } from "@/lib/locale-navigation";
import { exampleChat, type Onboarding, type StartGoal } from "@/lib/onboarding-api";
import { getErrorMessage } from "@/lib/api-error";
import { StartTaskMenu } from "./start-task-menu";
import { StartTaskCanvas } from "./start-task-canvas";
import { StartSetup } from "./start-setup";
import styles from "./workbench.module.css";

export function StartTasks({ data }: { data: Onboarding }) {
  const t = useTranslations("start");
  const errors = useTranslations("errors");
  const state = useStart();
  const router = useRouter();
  const [goal, setGoal] = useState<StartGoal>(data.goal ?? "meeting");
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const [setupOpen, setSetupOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const active = useRef(true);
  const action = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  const agent = data.agents.find((item) => item.id === selectedAgent) ?? data.agents[0];
  const setupAgent = !agent ? data.setup_agent : null;
  const chatAgent = agent ?? setupAgent;
  const save = async (next: StartGoal, navigate: boolean) => {
    setSaving(true);
    try {
      await state.save.mutateAsync({ goal: next });
      if (navigate && chatAgent && active.current) router.push(exampleChat(chatAgent.id, next));
    } finally {
      if (active.current) setSaving(false);
    }
  };
  const choose = (next: StartGoal) => {
    setGoal(next);
    void save(next, false).catch(() => {
      /* The choice stays usable; the save error is shown below. */
    });
  };
  return (
    <div className={styles.workbench} data-goal={goal}>
      <StartTaskMenu goal={goal} savedGoal={data.goal} saving={saving} onChange={choose} />
      <section className={styles.canvas} aria-label={t(`examples.${goal}.title`)}>
        <StartTaskCanvas key={goal} goal={goal} />
        <footer className={styles.canvasFooter}>
          {agent ? (
            <div className={styles.agentChoice}>
              <Label htmlFor="start-agent">{t("agent")}</Label>
              <select
                id="start-agent"
                value={agent.id}
                onChange={(event) => setSelectedAgent(event.target.value)}
              >
                {data.agents.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </div>
          ) : (
            <p className={styles.actionHint}>
              {t(
                setupAgent
                  ? "workbench.setupChatHint"
                  : data.can_prepare
                    ? "workbench.connectionHint"
                    : "workbench.memberHint",
              )}
            </p>
          )}
          <Button
            ref={action}
            className={styles.primaryAction}
            disabled={saving && !!chatAgent}
            aria-busy={saving && !!chatAgent}
            onClick={() => {
              if (!chatAgent) setSetupOpen(true);
              else
                void save(goal, true).catch(() => {
                  /* The mutation error is rendered below. */
                });
            }}
          >
            {setupAgent
              ? t("workbench.setupChat", { agent: setupAgent.name })
              : t(
                  agent
                    ? "tryExample"
                    : data.can_prepare
                      ? "workbench.connect"
                      : "workbench.getAccess",
                )}
            {saving && chatAgent ? (
              <LoaderCircle
                size={16}
                className="animate-spin motion-reduce:animate-none"
                aria-hidden
              />
            ) : (
              <ArrowRight size={16} aria-hidden />
            )}
          </Button>
        </footer>
        {state.save.error && (
          <p role="alert" className={styles.error}>
            {t("choiceNotSaved")} {getErrorMessage(state.save.error, errors)}
          </p>
        )}
      </section>
      <StartSetup
        data={data}
        open={setupOpen}
        onOpenChange={setSetupOpen}
        onReturnFocus={() => action.current?.focus()}
      />
    </div>
  );
}
