"use client";

import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { useExternalAgentOptions } from "@/hooks/use-desktop";
import type { ExternalAgent, LocalTarget } from "@/lib/desktop/commands";

type Runtime = NonNullable<LocalTarget["conversation_runtime"]>;

export function NativeConversationControl({
  target,
  onChange,
  codexEnabled,
  claudeEnabled,
  antigravityEnabled = false,
  antigravityRegistrations = [],
}: {
  target: LocalTarget;
  codexEnabled: boolean;
  claudeEnabled: boolean;
  antigravityEnabled?: boolean;
  /** Antigravity registrations on this Desktop; the runtime needs one to launch. */
  antigravityRegistrations?: ExternalAgent[];
  onChange: (target: LocalTarget) => void;
}) {
  const t = useTranslations("chat.controls.workOn");
  if (target.mode !== "full_access") return null;
  const runtime = target.conversation_runtime;
  const firstRegistration = antigravityRegistrations[0]?.id;
  // Any choice starts a new native session: identity includes harness, model and registration.
  const choose = (next: Runtime | null) =>
    onChange({ ...target, conversation_runtime: next, model_service: null });
  return (
    <div className="space-y-2 border-t py-3">
      <label className="block text-xs">
        {t("primaryRuntime")}
        <NativeSelect
          aria-label={t("primaryRuntime")}
          className="mt-1"
          value={runtime?.harness ?? "agent"}
          onChange={(event) => {
            const harness = event.target.value;
            if (harness === "codex" || harness === "claude_code")
              choose({ harness, session_epoch: crypto.randomUUID(), access: "read_only" });
            else if (harness === "antigravity" && firstRegistration !== undefined)
              choose({
                harness,
                session_epoch: crypto.randomUUID(),
                access: "edit",
                registration_id: firstRegistration,
              });
            else choose(null);
          }}
        >
          <option value="agent">{t("agentModel")}</option>
          <option value="codex" disabled={!codexEnabled}>
            {t("nativeCodex")}
          </option>
          <option value="claude_code" disabled={!claudeEnabled}>
            {t("nativeClaude")}
          </option>
          <option
            value="antigravity"
            disabled={!antigravityEnabled || firstRegistration === undefined}
          >
            {t("nativeAntigravity")}
          </option>
        </NativeSelect>
      </label>
      {(!codexEnabled || !claudeEnabled || !antigravityEnabled) && (
        <p className="text-muted-foreground text-xs">{t("primaryRuntimeDisabled")}</p>
      )}
      {antigravityEnabled && firstRegistration === undefined && (
        <p className="text-muted-foreground text-xs">{t("antigravityNotRegistered")}</p>
      )}
      {runtime?.harness === "antigravity" && (
        <AntigravityChoices
          runtime={runtime}
          registrations={antigravityRegistrations}
          onChange={(next) => choose({ ...next, session_epoch: crypto.randomUUID() })}
        />
      )}
      {runtime && (
        <>
          <p className="text-muted-foreground text-xs">{t("primaryRuntimeHelp")}</p>
          {runtime.harness !== "antigravity" && (
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
          )}
          {runtime.harness !== "antigravity" && (
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
          )}
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

/** Which registration, and which of its signed-in account's models, answer this chat. */
function AntigravityChoices({
  runtime,
  registrations,
  onChange,
}: {
  runtime: Runtime;
  registrations: ExternalAgent[];
  onChange: (runtime: Runtime) => void;
}) {
  const t = useTranslations("chat.controls.workOn");
  const options = useExternalAgentOptions(runtime.registration_id ?? null);
  const models = options.data?.models ?? [];
  return (
    <div className="space-y-2">
      {registrations.length > 1 && (
        <label className="block text-xs">
          {t("antigravityRegistration")}
          <NativeSelect
            aria-label={t("antigravityRegistration")}
            className="mt-1"
            value={runtime.registration_id ?? ""}
            onChange={(event) =>
              onChange({ ...runtime, registration_id: event.target.value, model_id: null })
            }
          >
            {registrations.map((registration) => (
              <option key={registration.id} value={registration.id}>
                {registration.name}
              </option>
            ))}
          </NativeSelect>
        </label>
      )}
      <label className="block text-xs">
        {t("antigravityModel")}
        <NativeSelect
          aria-label={t("antigravityModel")}
          className="mt-1"
          disabled={!options.isSuccess}
          value={runtime.model_id ?? ""}
          onChange={(event) => onChange({ ...runtime, model_id: event.target.value || null })}
        >
          <option value="">
            {options.data?.current_model
              ? t("antigravityAccountDefault", { model: options.data.current_model })
              : t("antigravityAccountDefaultUnknown")}
          </option>
          {models.map((model) => (
            <option key={model.value} value={model.value}>
              {model.name}
            </option>
          ))}
        </NativeSelect>
      </label>
      {options.isPending && runtime.registration_id && (
        <p className="text-muted-foreground text-xs">{t("antigravityModelsLoading")}</p>
      )}
      {options.isError && (
        <div className="space-y-1">
          <p role="alert" className="text-destructive text-xs">
            {options.error instanceof Error ? options.error.message : t("antigravityModelsFailed")}
          </p>
          <Button type="button" size="sm" variant="outline" onClick={() => options.refetch()}>
            {t("antigravityModelsRetry")}
          </Button>
        </div>
      )}
      <p className="text-muted-foreground text-xs">{t("antigravityHelp")}</p>
    </div>
  );
}
