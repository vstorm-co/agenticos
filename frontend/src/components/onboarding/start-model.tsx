"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { ModelProfilePicker } from "@/components/agents/model-profile-picker";
import { Button } from "@/components/ui";
import { useModelProviders } from "@/hooks/use-model-providers";
import { useStart } from "@/hooks/use-start";
import { LoaderCircle, PlugZap, ShieldCheck } from "lucide-react";
import styles from "./start.module.css";
import { getErrorMessage } from "@/lib/api-error";

export function StartModel({
  allowAdd,
  onPrepared,
}: {
  allowAdd: boolean;
  onPrepared: () => void;
}) {
  const t = useTranslations("start");
  const errors = useTranslations("errors");
  const [model, setModel] = useState<string | null>(null);
  const models = useModelProviders();
  const { prepare } = useStart();
  return (
    <div className="space-y-4">
      <p className={styles.note}>
        <ShieldCheck size={14} aria-hidden />
        {t("localPrivacy")}
      </p>
      <ModelProfilePicker
        profiles={models.profiles}
        profilesStatus={models.profilesStatus}
        value={model}
        onChange={setModel}
        allowAdd={allowAdd}
      />
      {prepare.error && (
        <p role="alert" className="text-destructive text-sm">
          {getErrorMessage(prepare.error, errors)}
        </p>
      )}
      <Button
        disabled={!model || prepare.isPending}
        onClick={() => {
          if (model) prepare.mutate(model, { onSuccess: onPrepared });
        }}
      >
        {prepare.isPending ? (
          <LoaderCircle size={16} className="animate-spin motion-reduce:animate-none" aria-hidden />
        ) : (
          <PlugZap size={16} aria-hidden />
        )}
        {t(prepare.isPending ? "preparing" : "prepare")}
      </Button>
      <p className="text-muted-foreground text-xs">{t("prepareHint")}</p>
    </div>
  );
}
