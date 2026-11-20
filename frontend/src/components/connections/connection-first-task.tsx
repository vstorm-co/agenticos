"use client";

import { useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { ArrowRight } from "lucide-react";
import { Button, Label } from "@/components/ui";
import { useAssistant } from "@/hooks/use-assistant";
import { isCurrentAppConnectionScope } from "@/hooks/use-app-connections";
import {
  appConnectionLabel,
  appConnectionUsable,
  GOAL_TOOLKITS,
  type AppConnectionGoal,
} from "@/lib/app-connection-journey";
import { useArchitectAskStore } from "@/stores/architect-ask-store";
import type { AppConnection, AppConnectionScope } from "@/types/app-connections";
import { ROUTES } from "@/lib/constants";

export function ConnectionFirstTask({
  goal,
  connections,
  scope,
  onConnect,
}: {
  goal: AppConnectionGoal;
  connections: AppConnection[];
  scope: AppConnectionScope;
  onConnect: () => void;
}) {
  const t = useTranslations("appConnections");
  const { assistant, isLoading, error, retry } = useAssistant();
  const [selectedId, setSelectedId] = useState("");
  const [sent, setSent] = useState(false);
  const eligible = connections.filter(appConnectionUsable);
  const selected =
    eligible.find((connection) => connection.id === selectedId) ??
    eligible.find((connection) => connection.is_default) ??
    eligible[0];
  const matchesGoal = selected && GOAL_TOOLKITS[goal].includes(selected.toolkit);
  const canAsk =
    !error && assistant?.status === "ready" && assistant.can_use && assistant.agent_id !== null;
  function ask() {
    if (!selected || !canAsk || !isCurrentAppConnectionScope(scope)) return;
    useArchitectAskStore.getState().ask(
      t(matchesGoal ? `goals.${goal}.prompt` : "exploreAppPrompt", {
        toolkit: selected.toolkit,
        account: appConnectionLabel(selected),
        connection: selected.id,
        catalog: selected.catalog_key,
      }),
      scope,
    );
    setSent(true);
  }
  return (
    <section className="space-y-4" data-tour="app-connection-first-task">
      <div>
        <h2 className="text-lg font-medium">{t("firstTaskTitle")}</h2>
        <p className="text-muted-foreground mt-1 text-sm">{t("firstTaskHint")}</p>
      </div>
      {!selected ? (
        <div className="space-y-3">
          <p className="text-muted-foreground text-sm">{t("firstTaskNeedsAccount")}</p>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" onClick={onConnect}>
              {t("chooseApps")}
            </Button>
            <Button variant="ghost" asChild>
              <Link href={ROUTES.CHAT}>{t("continueWithoutApps")}</Link>
            </Button>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="max-w-lg space-y-2">
            <Label htmlFor="first-task-account">{t("useAccount")}</Label>
            <select
              id="first-task-account"
              className="border-input bg-background h-10 w-full rounded-lg border px-3 text-sm"
              value={selected.id}
              onChange={(event) => {
                setSelectedId(event.target.value);
                setSent(false);
              }}
            >
              {eligible.map((connection) => (
                <option key={connection.id} value={connection.id}>
                  {appConnectionLabel(connection)} · {connection.toolkit}
                </option>
              ))}
            </select>
          </div>
          {!isLoading && !canAsk && (
            <p className="text-muted-foreground text-sm">{t("assistantUnavailable")}</p>
          )}
          {error && (
            <Button variant="outline" onClick={retry}>
              {t("retry")}
            </Button>
          )}
          {assistant?.can_use && (
            <Button disabled={!canAsk || isLoading || sent} onClick={ask}>
              {t(matchesGoal ? `goals.${goal}.title` : "exploreApp")}
              <ArrowRight aria-hidden />
            </Button>
          )}
          {sent && (
            <p role="status" className="text-muted-foreground text-sm">
              {t("taskSent")}
            </p>
          )}
        </div>
      )}
    </section>
  );
}
