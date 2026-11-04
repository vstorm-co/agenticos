"use client";

import { useTranslations } from "next-intl";
import { BackgroundTaskList } from "@/components/chat/background-tasks";
import { useConversationTasks } from "@/hooks/use-conversation-tasks";
import { WidgetFrame } from "../widget-frame";
import { WidgetSkeleton, WidgetErrorBody, WidgetEmptyBody } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

export function BackgroundTasksWidget({ title, hint, seeAll, options }: DashboardWidgetProps) {
  const t = useTranslations("chat.backgroundTasks");
  const state = useConversationTasks(null);
  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll} options={options}>
      {state.isPending ? (
        <WidgetSkeleton />
      ) : state.error || !state.data ? (
        <WidgetErrorBody onRetry={() => void state.refetch()} />
      ) : state.data.length === 0 ? (
        <WidgetEmptyBody title={t("emptyTitle")} description={t("empty")} />
      ) : (
        <BackgroundTaskList
          tasks={state.data}
          stopping={state.stop.isPending}
          onStop={(id) => state.stop.mutate(id)}
        />
      )}
    </WidgetFrame>
  );
}
