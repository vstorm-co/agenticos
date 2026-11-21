"use client";

import { CopilotModelConnection } from "./copilot-model-connection";
import { useId, useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Input, Label } from "@/components/ui";
import { usePersonalModelKeys } from "@/hooks/use-personal-model-keys";
import { useChanged } from "@/hooks/use-changed";
import type { PersonalModelDestination } from "@/lib/personal-model-keys-api";
import { getErrorMessage } from "@/lib/api-error";

export function PersonalModelConnection({
  agentId,
  manage = false,
}: {
  agentId: string | null;
  manage?: boolean;
}) {
  const t = useTranslations("personalModelKeys");
  const errors = useTranslations("errors");
  const common = useTranslations("common");
  const id = useId();
  const [key, setKey] = useState("");
  const { status, save } = usePersonalModelKeys(agentId);
  const connection = status.data;
  const destination: PersonalModelDestination | null =
    connection?.personal && connection.profile_id && connection.provider && connection.model
      ? {
          profile_id: connection.profile_id,
          provider: connection.provider,
          endpoint: connection.endpoint,
          model: connection.model,
        }
      : null;
  if (useChanged(`${agentId}|${JSON.stringify(destination)}`)) setKey("");
  if (status.isError)
    return (
      <div role="alert" className="space-y-2 text-sm">
        <p>{getErrorMessage(status.error, errors)}</p>
        <Button type="button" size="sm" variant="outline" onClick={() => void status.refetch()}>
          {common("retry")}
        </Button>
      </div>
    );
  if (!connection || !destination || !agentId || (connection.connected && !manage)) return null;
  if (destination.provider === "github_copilot")
    return (
      <CopilotModelConnection
        agentId={agentId}
        destination={destination}
        connected={connection.connected}
      />
    );
  return (
    <form
      method="post"
      aria-label={t("title")}
      className="space-y-3 p-3"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate(
          { agentId, api_key: key, expected_destination: destination },
          { onSuccess: () => setKey("") },
        );
      }}
    >
      <p className="text-sm font-medium">{t("title")}</p>
      <p className="text-muted-foreground text-xs">
        {t("fixed", {
          model: destination.model,
          endpoint: destination.endpoint ?? destination.provider,
        })}
      </p>
      <p role="status" className="text-muted-foreground text-xs">
        {t(connection.connected ? "connected" : "required")}
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
          autoCorrect="off"
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
        {t(connection.connected ? "replace" : "connect")}
      </Button>
      <p className="text-muted-foreground text-xs">{t("privacy")}</p>
    </form>
  );
}
