"use client";

import { useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import { usePersonalModelKeys } from "@/hooks/use-personal-model-keys";
import { getErrorMessage } from "@/lib/api-error";

export function PersonalModelKeys() {
  const t = useTranslations("personalModelKeys");
  const errors = useTranslations("errors");
  const { keys, remove } = usePersonalModelKeys();
  return (
    <section aria-label={t("title")} className="bg-card space-y-3 rounded-xl border p-5">
      <h2 className="text-sm font-medium">{t("title")}</h2>
      <p className="text-muted-foreground text-xs">{t("vaultHelp")}</p>
      {keys.isPending && <p role="status">{t("loading")}</p>}
      {(keys.error || remove.error) && (
        <p role="alert">{getErrorMessage(keys.error ?? remove.error, errors)}</p>
      )}
      {keys.data?.items.map((key) => (
        <div key={key.id} className="flex items-center justify-between gap-3">
          <span className="text-sm">
            {key.provider} · {key.endpoint || t("defaultEndpoint")}
          </span>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={remove.isPending}
            onClick={() => remove.mutate(key.id)}
          >
            {t("remove")}
          </Button>
        </div>
      ))}
    </section>
  );
}
