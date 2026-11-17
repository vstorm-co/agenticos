"use client";

import { useId, useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Input, Label } from "@/components/ui";
import { usePersonalModelKeys } from "@/hooks/use-personal-model-keys";
import { getErrorMessage } from "@/lib/api-error";

export function PersonalModelConnection({ agentId }: { agentId: string | null }) {
  const t = useTranslations("personalModelKeys");
  const errors = useTranslations("errors");
  const id = useId();
  const [key, setKey] = useState("");
  const { status, save } = usePersonalModelKeys(agentId);
  if (status.isError) return <p role="alert">{getErrorMessage(status.error, errors)}</p>;
  if (!status.data?.personal || !agentId) return null;
  return (
    <form
      method="post"
      aria-label={t("title")}
      className="space-y-3 p-3"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate({ agentId, api_key: key }, { onSuccess: () => setKey("") });
      }}
    >
      <p className="text-sm font-medium">{t("title")}</p>
      <p className="text-muted-foreground text-xs">
        {t("fixed", {
          model: status.data.model ?? "",
          endpoint: status.data.endpoint ?? status.data.provider ?? "",
        })}
      </p>
      <p role="status" className="text-muted-foreground text-xs">
        {t(status.data.connected ? "connected" : "required")}
      </p>
      <div className="space-y-1">
        <Label htmlFor={id}>{t("key")}</Label>
        <Input
          id={id}
          name="api_key"
          type="password"
          required
          minLength={8}
          maxLength={8192}
          disabled={save.isPending}
          autoComplete="new-password"
          autoCapitalize="none"
          spellCheck={false}
          value={key}
          onChange={(event) => setKey(event.target.value)}
        />
      </div>
      {save.isError && (
        <p role="alert" className="text-destructive text-xs">
          {getErrorMessage(save.error, errors)}
        </p>
      )}
      <Button type="submit" size="sm" disabled={save.isPending}>
        {t(status.data.connected ? "replace" : "connect")}
      </Button>
      <p className="text-muted-foreground text-xs">{t("privacy")}</p>
    </form>
  );
}
