"use client";

import { useRef, useState } from "react";
import { ArrowLeft, ArrowRight } from "lucide-react";
import { useTranslations } from "next-intl";
import { ChatModelPicker } from "@/components/chat/chat-model-picker";
import { ProviderIcon } from "@/components/vault/provider-icon";
import { Button, Skeleton } from "@/components/ui";
import { useProviderCatalog } from "@/hooks/use-model-providers";
import { usePermissions } from "@/hooks/use-permissions";
import { useSavedChatControls } from "@/hooks/use-saved-chat-controls";
import { Perm } from "@/types/permissions";
import { StartAvailableModels } from "./start-available-models";
import { StartProviderSetup } from "./start-provider-setup";
import styles from "./start-models.module.css";

const FIRST_PROVIDERS = ["openrouter", "anthropic", "openai", "google"];

/** Provider discovery comes before account configuration and a model catalog. */
export function StartModels() {
  const t = useTranslations("start.modelSetup");
  const shared = useTranslations("start.experience");
  const picker = useTranslations("chat.modelPicker");
  const common = useTranslations("common");
  const catalog = useProviderCatalog();
  const {
    can,
    isLoading: permissionsLoading,
    error: permissionError,
    refetch: refetchPermissions,
  } = usePermissions();
  const controls = useSavedChatControls();
  const [providerId, setProviderId] = useState<string | null>(null);
  const content = useRef<HTMLDivElement>(null);
  function chooseProvider(id: string | null) {
    setProviderId(id);
    const viewport = content.current?.closest<HTMLElement>("[data-start-content]");
    if (viewport) viewport.scrollTop = 0;
  }
  const providers = (catalog.data?.items ?? [])
    .filter(
      (entry) =>
        !entry.personal_gateway &&
        entry.secret_kind !== "openai_codex" &&
        entry.secret_kind !== "openai_chatgpt",
    )
    .sort((a, b) => {
      const rank = (id: string) =>
        FIRST_PROVIDERS.includes(id) ? FIRST_PROVIDERS.indexOf(id) : FIRST_PROVIDERS.length;
      return rank(a.id) - rank(b.id) || a.name.localeCompare(b.name);
    });
  const provider = providers.find((entry) => entry.id === providerId);
  if (catalog.isLoading || permissionsLoading)
    return (
      <div role="status" aria-label={common("loading")} className={styles.providers}>
        {Array.from({ length: 6 }, (_, index) => (
          <Skeleton key={index} className="h-28 rounded-xl" />
        ))}
      </div>
    );
  if (catalog.error || permissionError)
    return (
      <div role="alert" className={styles.failure}>
        <p>{t("loadFailed")}</p>
        <Button
          type="button"
          variant="outline"
          onClick={() => {
            void catalog.refetch();
            void refetchPermissions();
          }}
        >
          {common("retry")}
        </Button>
      </div>
    );
  if (!can(Perm.connectionsManage))
    return (
      <div className={styles.setup}>
        <StartAvailableModels providers={providers.map((entry) => entry.id)} />
        <p className={styles.scope}>{shared("modelsScope")}</p>
      </div>
    );
  return (
    <div ref={content} className={styles.setup} data-start-model-setup>
      {provider ? (
        <>
          <div className={styles.providerHeading}>
            <Button type="button" variant="ghost" size="sm" onClick={() => chooseProvider(null)}>
              <ArrowLeft aria-hidden className="size-4" />
              {t("changeProvider")}
            </Button>
            <span className={styles.selectedProvider}>
              <ProviderIcon provider={provider.id} className="size-5" />
              {provider.name}
            </span>
          </div>
          <ChatModelPicker
            key={provider.id}
            presentation="library"
            providerView={{ id: provider.id, component: StartProviderSetup }}
            value={controls.modelProfileId}
            agentModel={null}
            onChange={(modelProfileId) => controls.update({ modelProfileId })}
          />
        </>
      ) : (
        <>
          <p className={styles.hint}>{t("chooseProvider")}</p>
          <div className={styles.providers} role="group" aria-label={picker("provider")}>
            {providers.map((entry) => (
              <button
                type="button"
                key={entry.id}
                className={styles.provider}
                onClick={() => chooseProvider(entry.id)}
              >
                <ProviderIcon provider={entry.id} className="size-8" />
                <span>{entry.name}</span>
                <ArrowRight className={styles.providerArrow} aria-hidden />
              </button>
            ))}
          </div>
          {providers.length === 0 && (
            <p role="status" className={styles.hint}>
              {t("noProviders")}
            </p>
          )}
        </>
      )}
      <p className={styles.scope}>{shared("modelsScope")}</p>
    </div>
  );
}
