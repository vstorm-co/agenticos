"use client";

import type { ReactNode } from "react";
import { TriangleAlert } from "lucide-react";
import { useTranslations } from "next-intl";
import { Alert, AlertDescription } from "@/components/ui";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { useExternalAgentOptions } from "@/hooks/use-desktop";
import { useSecrets } from "@/hooks/use-secrets";
import { getErrorMessage } from "@/lib/api-error";
import type { ExternalAgent, LocalTarget } from "@/lib/desktop/commands";

type Runtime = NonNullable<LocalTarget["conversation_runtime"]>;

/** Pi speaks RPC, not ACP, so it only takes delegated tasks. */
const PI_PROVIDERS: ExternalAgent["provider"][] = [
  "pi",
  "pi_inception",
  "pi_deepseek",
  "pi_openrouter",
];
/** These choose their model themselves; Desktop cannot list it without a session of theirs. */
const SELF_CHOSEN_MODELS: ExternalAgent["provider"][] = [
  "mistral_vibe",
  "kimi",
  "qwen_subscription",
  "devin",
  "hermes",
  "muse",
  "muse_api_key",
];

/** Registrations that can answer a conversation, not only take delegated tasks. */
export function conversationRegistrations(registrations: ExternalAgent[]): ExternalAgent[] {
  return registrations.filter((registration) => !PI_PROVIDERS.includes(registration.provider));
}

export function NativeConversationControl({
  target,
  onChange,
  codexEnabled,
  claudeEnabled,
  externalEnabled = false,
  registrations = [],
}: {
  target: LocalTarget;
  codexEnabled: boolean;
  claudeEnabled: boolean;
  externalEnabled?: boolean;
  /** ACP registrations on this Desktop that can answer a conversation. */
  registrations?: ExternalAgent[];
  onChange: (target: LocalTarget) => void;
}) {
  const t = useTranslations("chat.controls.workOn");
  if (target.mode !== "full_access") return null;
  const runtime = target.conversation_runtime;
  const firstRegistration = registrations[0]?.id;
  // Any choice starts a new native session: identity includes harness, model and registration.
  const choose = (next: Runtime | null) =>
    onChange({ ...target, conversation_runtime: next, model_service: null });
  return (
    <div className="space-y-2 border-t py-3">
      <label className="block text-xs">
        {t("primaryRuntime")}
        <NativeSelect
          aria-label={t("primaryRuntime")}
          className="mt-1 px-2"
          value={runtime?.harness ?? "agent"}
          onChange={(event) => {
            const harness = event.target.value;
            if (harness === "codex" || harness === "claude_code")
              choose({ harness, session_epoch: crypto.randomUUID(), access: "read_only" });
            else if (harness === "external" && firstRegistration !== undefined)
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
          <option value="external" disabled={!externalEnabled || firstRegistration === undefined}>
            {t("nativeExternal")}
          </option>
        </NativeSelect>
      </label>
      {(!codexEnabled || !claudeEnabled || !externalEnabled) && (
        <p className="text-muted-foreground text-xs">{t("primaryRuntimeDisabled")}</p>
      )}
      {externalEnabled && firstRegistration === undefined && (
        <p className="text-muted-foreground text-xs">{t("externalNotRegistered")}</p>
      )}
      {runtime?.harness === "external" && (
        <ExternalChoices
          runtime={runtime}
          registrations={registrations}
          onChange={(next) => choose({ ...next, session_epoch: crypto.randomUUID() })}
        />
      )}
      {runtime && (
        <>
          <p className="text-muted-foreground text-xs">{t("primaryRuntimeHelp")}</p>
          <RuntimeNotice>{t("primaryRuntimeTerms")}</RuntimeNotice>
          {runtime.harness !== "external" && (
            <label className="block text-xs">
              {t("primaryRuntimeAccess")}
              <NativeSelect
                aria-label={t("primaryRuntimeAccess")}
                className="mt-1 px-2"
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
          {runtime.harness !== "external" && (
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

/** Which registration, and which of its sign-in's models, answer this chat. */
function ExternalChoices({
  runtime,
  registrations,
  onChange,
}: {
  runtime: Runtime;
  registrations: ExternalAgent[];
  onChange: (runtime: Runtime) => void;
}) {
  const t = useTranslations("chat.controls.workOn");
  const selected = registrations.find(
    (registration) => registration.id === runtime.registration_id,
  );
  const keyed = selected?.provider === "antigravity_api_key";
  const listed =
    selected !== undefined && !keyed && !SELF_CHOSEN_MODELS.includes(selected.provider);
  return (
    <div className="space-y-2">
      {registrations.length > 1 && (
        <label className="block text-xs">
          {t("externalRegistration")}
          <NativeSelect
            aria-label={t("externalRegistration")}
            className="mt-1 px-2"
            value={runtime.registration_id ?? ""}
            onChange={(event) =>
              onChange({
                ...runtime,
                registration_id: event.target.value,
                model_id: null,
                secret_id: null,
              })
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
      {selected?.provider === "antigravity_api_key" && (
        <VaultKeyChoice runtime={runtime} onChange={onChange} />
      )}
      {keyed ? (
        <label className="block text-xs">
          {t("primaryRuntimeModel")}
          <Input
            aria-label={t("primaryRuntimeModel")}
            className="mt-1"
            value={runtime.model_id ?? ""}
            onChange={(event) => onChange({ ...runtime, model_id: event.target.value || null })}
          />
        </label>
      ) : listed ? (
        <ExternalModels runtime={runtime} onChange={onChange} />
      ) : (
        <p className="text-muted-foreground text-xs">{t("externalCliModels")}</p>
      )}
      {selected?.provider === "antigravity" && (
        <RuntimeNotice>{t("antigravityPersonalRisk")}</RuntimeNotice>
      )}
      <p className="text-muted-foreground text-xs">{t("externalHelp")}</p>
    </div>
  );
}

/** The models the selected registration's own sign-in offers, read without a model turn. */
function ExternalModels({
  runtime,
  onChange,
}: {
  runtime: Runtime;
  onChange: (runtime: Runtime) => void;
}) {
  const t = useTranslations("chat.controls.workOn");
  const tErrors = useTranslations("errors");
  const options = useExternalAgentOptions(runtime.registration_id ?? null);
  const models = options.data?.models ?? [];
  return (
    <>
      <label className="block text-xs">
        {t("externalModel")}
        <NativeSelect
          aria-label={t("externalModel")}
          className="mt-1 px-2"
          disabled={!options.isSuccess}
          value={runtime.model_id ?? ""}
          onChange={(event) => onChange({ ...runtime, model_id: event.target.value || null })}
        >
          <option value="">
            {options.data?.current_model
              ? t("externalAccountDefault", { model: options.data.current_model })
              : t("externalAccountDefaultUnknown")}
          </option>
          {models.map((model) => (
            <option key={model.value} value={model.value}>
              {model.name}
            </option>
          ))}
        </NativeSelect>
      </label>
      {options.isPending && (
        <p className="text-muted-foreground text-xs">{t("externalModelsLoading")}</p>
      )}
      {options.isError && (
        <div className="space-y-1">
          <p role="alert" className="text-destructive text-xs">
            {getErrorMessage(options.error, tErrors, t("externalModelsFailed"))}
          </p>
          <Button type="button" size="sm" variant="outline" onClick={() => options.refetch()}>
            {t("externalModelsRetry")}
          </Button>
        </div>
      )}
    </>
  );
}

/** A Gemini key from the vault for this run, or the key Desktop inherited. */
function VaultKeyChoice({
  runtime,
  onChange,
}: {
  runtime: Runtime;
  onChange: (runtime: Runtime) => void;
}) {
  const t = useTranslations("chat.controls.workOn");
  const { secrets, listError } = useSecrets();
  const keys = secrets.filter(
    (secret) =>
      secret.kind === "api_key" && (secret.purpose === "google" || secret.purpose === "custom"),
  );
  return (
    <>
      <label className="block text-xs">
        {t("geminiVaultKey")}
        <NativeSelect
          aria-label={t("geminiVaultKey")}
          className="mt-1 px-2"
          value={runtime.secret_id ?? ""}
          onChange={(event) => onChange({ ...runtime, secret_id: event.target.value || null })}
        >
          <option value="">{t("geminiDesktopKey")}</option>
          {keys.map((secret) => (
            <option key={secret.id} value={secret.id}>
              {secret.name}
            </option>
          ))}
        </NativeSelect>
      </label>
      {listError ? (
        <p className="text-muted-foreground text-xs">{t("geminiVaultUnavailable")}</p>
      ) : null}
    </>
  );
}

/** A provider-terms warning in the runtime picker: the account and its risk are the person's. */
function RuntimeNotice({ children }: { children: ReactNode }) {
  return (
    <Alert role="note" variant="warning" className="p-3 [&>svg]:top-3 [&>svg]:left-3">
      <TriangleAlert aria-hidden className="size-4" />
      <AlertDescription className="text-xs">{children}</AlertDescription>
    </Alert>
  );
}
