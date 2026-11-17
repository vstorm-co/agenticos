"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { ErrorState } from "@/components/states";
import { CopyableValue } from "@/components/workflows/triggers/copyable-value";
import { useEventSources } from "@/hooks/use-event-sources";
import { usePermissions } from "@/hooks/use-permissions";
import type { EventSource, EventSourceCreated } from "@/lib/event-sources-api";
import { Perm } from "@/types/permissions";
import { SourceForm } from "./source-form";

export function SourceSelector({
  value,
  onChange,
  allowDedicated = false,
  disabled = false,
}: {
  value: string | null;
  onChange: (source: EventSource | null) => void;
  allowDedicated?: boolean;
  disabled?: boolean;
}) {
  const t = useTranslations("eventSources");
  const { can } = usePermissions();
  const sources = useEventSources();
  const [creating, setCreating] = useState(false);
  const [created, setCreated] = useState<EventSourceCreated | null>(null);
  const selected =
    sources.data?.items.find((source) => source.id === value) ??
    (created?.id === value ? created : null);
  return (
    <div className="space-y-3" data-tour="event-source-select">
      <Label htmlFor="event-source-select">{t("selectSource")}</Label>
      {sources.error ? (
        <ErrorState
          description={t("loadError")}
          cta={{ label: t("retry"), onClick: () => void sources.refetch() }}
        />
      ) : (
        <Select
          value={value ?? "dedicated"}
          disabled={disabled || sources.isLoading}
          onValueChange={(id) => {
            setCreated(null);
            onChange(sources.data?.items.find((source) => source.id === id) ?? null);
          }}
        >
          <SelectTrigger id="event-source-select">
            <SelectValue placeholder={t("selectSource")} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="dedicated" disabled={!allowDedicated}>
              {allowDedicated ? t("dedicated") : t("chooseSource")}
            </SelectItem>
            {sources.data?.items
              .filter((source) => source.can_use || source.id === value)
              .map((source) => (
                <SelectItem key={source.id} value={source.id} disabled={!source.can_use}>
                  {source.name}
                  {!source.is_active ? ` (${t("paused")})` : ""}
                </SelectItem>
              ))}
          </SelectContent>
        </Select>
      )}
      {selected && (
        <CopyableValue id="source-live-url" label={t("liveUrl")} value={selected.webhook_url} />
      )}
      {created?.reveal_secret && (
        <div className="rounded-md border p-3">
          <p className="text-sm">{t("revealOnce")}</p>
          <CopyableValue
            id="source-reveal-secret"
            label={t("secret")}
            value={created.reveal_secret}
          />
        </div>
      )}
      {can(Perm.eventSourcesEdit) &&
        !disabled &&
        (creating ? (
          <SourceForm
            onCancel={() => setCreating(false)}
            onSaved={(source) => {
              setCreated(source);
              onChange(source);
              setCreating(false);
            }}
          />
        ) : (
          <Button type="button" variant="outline" onClick={() => setCreating(true)}>
            {t("createNew")}
          </Button>
        ))}
    </div>
  );
}
