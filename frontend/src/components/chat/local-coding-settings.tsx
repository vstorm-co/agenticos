"use client";

import { useId } from "react";
import { useTranslations } from "next-intl";
import { useLocalCodingOptions } from "@/hooks/use-desktop";
import type { LocalAgent } from "@/lib/desktop/commands";
import { useWorkOnStore, type CodingPreferences } from "@/stores/work-on-store";
import { useConversationStore } from "@/stores";
import { getErrorMessage } from "@/lib/api-error";
import { Button } from "@/components/ui/button";

/** Choices come from the installed harness; leaving either unset retains its settings. */
export function LocalCodingSettings({ harness }: { harness: LocalAgent["id"] }) {
  const t = useTranslations("chat.controls.workOn.coding");
  const tReasoning = useTranslations("chat.reasoning");
  const tErrors = useTranslations("errors");
  const id = useId();
  const conversationId = useConversationStore((state) => state.currentConversationId);
  const preferences = useWorkOnStore((state) => state.codingPreferencesFor(conversationId));
  const state = useLocalCodingOptions(harness);
  const save = (next: CodingPreferences) => {
    const store = useWorkOnStore.getState();
    store.setCoding(conversationId, harness);
    store.setCodingPreferences(conversationId, next);
  };
  if (!state.data)
    return (
      <div className="text-muted-foreground mt-3 text-xs" role="status">
        {state.error ? (
          <>
            <p>{getErrorMessage(state.error, tErrors)}</p>
            <Button
              size="sm"
              variant="ghost"
              disabled={state.isFetching}
              onClick={() => void state.refetch()}
            >
              {t("refreshSettings")}
            </Button>
          </>
        ) : (
          t("loadingSettings")
        )}
      </div>
    );
  const data = state.data;
  const { models } = data;
  const selected = models.find(
    (model) => model.value === (preferences.model ?? data.current_model),
  );
  const efforts = selected?.efforts ?? [];
  const missingModel =
    preferences.model !== null && !models.some((model) => model.value === preferences.model);
  const missingEffort =
    preferences.effort !== null && !efforts.some((effort) => effort.value === preferences.effort);
  return (
    <div
      className="mt-3 grid grid-cols-[repeat(auto-fit,minmax(min(100%,12rem),1fr))] gap-2"
      data-tour="chat-coding-settings"
    >
      <div className="min-w-0 space-y-1">
        <label htmlFor={`${id}-model`} className="text-muted-foreground text-xs">
          {t("model")}
        </label>
        <select
          id={`${id}-model`}
          value={preferences.model ?? ""}
          className="bg-background border-input h-8 w-full rounded-md border px-2 text-xs"
          onChange={(event) => {
            const model = event.target.value || null;
            const next = models.find((entry) => entry.value === (model ?? data.current_model));
            save({
              model,
              effort: next?.efforts.some((entry) => entry.value === preferences.effort)
                ? preferences.effort
                : null,
            });
          }}
        >
          <option value="">{t("ownModel")}</option>
          {missingModel && (
            <option value={preferences.model ?? ""}>
              {t("unavailableOption", { value: preferences.model ?? "" })}
            </option>
          )}
          {models.map((model) => (
            <option key={model.value} value={model.value}>
              {model.name}
            </option>
          ))}
        </select>
      </div>
      <div className="min-w-0 space-y-1">
        <label htmlFor={`${id}-effort`} className="text-muted-foreground text-xs">
          {t("effort")}
        </label>
        <select
          id={`${id}-effort`}
          value={preferences.effort ?? ""}
          disabled={efforts.length === 0 && preferences.effort === null}
          className="bg-background border-input h-8 w-full rounded-md border px-2 text-xs disabled:opacity-50"
          onChange={(event) => save({ ...preferences, effort: event.target.value || null })}
        >
          <option value="">{efforts.length === 0 ? t("effortUnsupported") : t("ownEffort")}</option>
          {missingEffort && (
            <option value={preferences.effort ?? ""}>
              {t("unavailableOption", { value: preferences.effort ?? "" })}
            </option>
          )}
          {efforts.map((effort) => (
            <option key={effort.value} value={effort.value}>
              {tReasoning.has(`levels.${effort.value}`)
                ? tReasoning(`levels.${effort.value}`)
                : effort.name}
            </option>
          ))}
        </select>
      </div>
      <div className="col-span-full">
        {state.error && (
          <p className="text-destructive text-xs" role="alert">
            {getErrorMessage(state.error, tErrors)}
          </p>
        )}
        <Button
          size="sm"
          variant="ghost"
          className="h-6 px-0 text-xs"
          disabled={state.isFetching}
          onClick={() => void state.refetch()}
        >
          {t("refreshSettings")}
        </Button>
      </div>
    </div>
  );
}
