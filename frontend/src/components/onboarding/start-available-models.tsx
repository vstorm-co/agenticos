"use client";

import { Check } from "lucide-react";
import { useTranslations } from "next-intl";
import { Button, Skeleton } from "@/components/ui";
import { ModelIcon } from "@/components/icons/model-icon";
import { useModelProviders } from "@/hooks/use-model-providers";
import { useSavedChatControls } from "@/hooks/use-saved-chat-controls";
import { modelName, usableForAgents } from "@/lib/model-profiles";
import styles from "./start-models.module.css";

/** Members can use a configured workspace model without changing its credentials. */
export function StartAvailableModels({ providers }: { providers: readonly string[] }) {
  const t = useTranslations("start.modelSetup");
  const picker = useTranslations("chat.modelPicker");
  const common = useTranslations("common");
  const models = useModelProviders({ silentCreate: true });
  const controls = useSavedChatControls();
  const profiles = models.profiles.filter(
    (entry) => providers.includes(entry.provider) && usableForAgents(entry),
  );
  if (models.isLoading) return <Skeleton className="h-28 rounded-xl" />;
  if (models.profilesStatus === "failed")
    return (
      <div role="alert" className={styles.failure}>
        <p>{picker("profilesUnavailable")}</p>
        <Button type="button" variant="outline" onClick={() => void models.refetchProfiles()}>
          {common("retry")}
        </Button>
      </div>
    );
  return (
    <div className={styles.stage}>
      <p className={styles.hint}>{t("existingModels")}</p>
      <div role="group" aria-label={picker("allModels")} className={styles.stage}>
        {profiles.map((profile) => (
          <button
            type="button"
            key={profile.id}
            className={styles.savedModel}
            aria-pressed={profile.id === controls.modelProfileId}
            onClick={() => controls.update({ modelProfileId: profile.id })}
          >
            <ModelIcon model={profile.model} provider={profile.provider} />
            <span>{modelName(profile)}</span>
            {profile.id === controls.modelProfileId && <Check aria-hidden className="size-4" />}
          </button>
        ))}
      </div>
      {profiles.length === 0 && (
        <p role="status" className={styles.hint}>
          {t("noExistingModels")}
        </p>
      )}
    </div>
  );
}
