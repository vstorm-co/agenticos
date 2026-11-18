"use client";

import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import type { LocalTarget } from "@/lib/desktop/commands";

export function NativeConversationControl({
  target,
  onChange,
  codexEnabled,
}: {
  target: LocalTarget;
  codexEnabled: boolean;
  onChange: (target: LocalTarget) => void;
}) {
  const t = useTranslations("chat.controls.workOn");
  if (target.mode !== "full_access") return null;
  const runtime = target.conversation_runtime;
  return (
    <div className="space-y-2 border-t py-3">
      <label className="block text-xs">
        {t("primaryRuntime")}
        <NativeSelect
          aria-label={t("primaryRuntime")}
          className="mt-1"
          value={runtime?.harness ?? "agent"}
          onChange={(event) =>
            onChange({
              ...target,
              conversation_runtime:
                event.target.value === "codex"
                  ? { harness: "codex", session_epoch: crypto.randomUUID(), access: "read_only" }
                  : null,
              model_service: null,
            })
          }
        >
          <option value="agent">{t("agentModel")}</option>
          <option value="codex" disabled={!codexEnabled}>
            {t("nativeCodex")}
          </option>
        </NativeSelect>
      </label>
      {!codexEnabled && (
        <p className="text-muted-foreground text-xs">{t("primaryRuntimeDisabled")}</p>
      )}
      {runtime && (
        <>
          <p className="text-muted-foreground text-xs">{t("primaryRuntimeHelp")}</p>
          <label className="block text-xs">
            {t("primaryRuntimeAccess")}
            <NativeSelect
              aria-label={t("primaryRuntimeAccess")}
              className="mt-1"
              value={runtime.access}
              onChange={(event) => {
                const access = event.target.value;
                if (access === "read_only" || access === "edit")
                  onChange({
                    ...target,
                    conversation_runtime: {
                      ...runtime,
                      access,
                      session_epoch: crypto.randomUUID(),
                    },
                  });
              }}
            >
              <option value="read_only">{t("mode.read_only")}</option>
              <option value="edit">{t("primaryRuntimeEdit")}</option>
            </NativeSelect>
          </label>
          <label className="block text-xs">
            {t("primaryRuntimeModel")}
            <Input
              aria-label={t("primaryRuntimeModel")}
              className="mt-1 h-9"
              value={runtime.model_id ?? ""}
              onChange={(event) =>
                onChange({
                  ...target,
                  conversation_runtime: {
                    ...runtime,
                    model_id: event.target.value || null,
                    session_epoch: crypto.randomUUID(),
                  },
                })
              }
            />
          </label>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() =>
              onChange({
                ...target,
                conversation_runtime: { ...runtime, session_epoch: crypto.randomUUID() },
              })
            }
          >
            {t("primaryRuntimeReset")}
          </Button>
          <p className="text-muted-foreground text-xs">{t("primaryRuntimeResetHelp")}</p>
        </>
      )}
    </div>
  );
}
