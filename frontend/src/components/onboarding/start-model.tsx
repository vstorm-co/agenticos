"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { ModelProfilePicker } from "@/components/agents/model-profile-picker";
import { Button } from "@/components/ui";
import { useModelProviders } from "@/hooks/use-model-providers";
import { useStart } from "@/hooks/use-start";
import { getErrorMessage } from "@/lib/api-error";

export function StartModel({ allowAdd }: { allowAdd: boolean }) {
  const t = useTranslations("start");
  const errors = useTranslations("errors");
  const [model, setModel] = useState<string | null>(null);
  const models = useModelProviders();
  const { prepare } = useStart();
  return (
    <section className="space-y-4 rounded-xl border p-5">
      <h2 className="text-lg font-semibold">{t("connectTitle")}</h2>
      <p className="text-muted-foreground text-sm">{t("connectHint")}</p>
      <p className="text-muted-foreground text-sm">{t("localPrivacy")}</p>
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
          if (model) prepare.mutate(model);
        }}
      >
        {t(prepare.isPending ? "preparing" : "prepare")}
      </Button>
      <p className="text-muted-foreground text-xs">{t("prepareHint")}</p>
    </section>
  );
}
