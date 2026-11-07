"use client";

import { useState } from "react";
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
    <div className="space-y-5">
      <p className="text-muted-foreground text-sm" role="status">
        {t(agent ? "ready" : "notReady")}
      </p>
      {agent && data.agents.length === 1 && (
        <p className="text-sm">
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
      <section aria-label={t("examplesTitle")}>
        <ul className="grid gap-3 md:grid-cols-3">
          {START_GOALS.map((goal) => (
            <li key={goal} className="flex flex-col gap-3 rounded-xl border p-5">
              <h2 className="font-semibold">{t(`examples.${goal}.title`)}</h2>
              <p className="text-muted-foreground flex-1 text-sm">
                {t(`examples.${goal}.description`)}
              </p>
              <Button
                variant={data.goal === goal ? "default" : "outline"}
                disabled={state.save.isPending}
                onClick={() => {
                  void choose(goal).catch(() => {
                    /* The mutation error stays visible below the choices. */
                  });
                }}
              >
                {t(agent ? "tryExample" : "showExample")}
              </Button>
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
          <section className="space-y-2 rounded-xl border p-5">
            <h2 className="font-semibold">{t("askOwner")}</h2>
            <p className="text-muted-foreground text-sm">{t("askOwnerHint")}</p>
            {data.support_email && (
              <a className="mr-3 text-sm underline" href={`mailto:${data.support_email}`}>
                {data.support_email}
              </a>
            )}
            <Button variant="outline" onClick={() => void state.refetch()}>
              {t("checkAgain")}
            </Button>
          </section>
        ))}
      {agent && data.can_prepare && (
        <details className="rounded-xl border p-4">
          <summary className="cursor-pointer text-sm">{t("connectTitle")}</summary>
          <div className="mt-4">
            <StartModel allowAdd={data.can_configure_model} />
          </div>
        </details>
      )}
      {agent && <p className="text-muted-foreground text-xs">{t("runNotice")}</p>}
    </div>
  );
}
