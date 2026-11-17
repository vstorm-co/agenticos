"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Label, Spinner, Textarea } from "@/components/ui";
import { CopyableValue } from "@/components/workflows/triggers/copyable-value";
import { useEventSource, useSourceListener } from "@/hooks/use-event-sources";
import type { EventSample } from "@/lib/event-sources-api";
import { MAX_PINNED_BYTES, jsonBytes } from "@/lib/workflows/step-data";

/** Live capture never changes subscriber dispatch; pasted examples never make deliveries. */
export function LiveSample({
  sourceId,
  onSample,
}: {
  sourceId: string;
  onSample: (sample: EventSample) => void;
}) {
  const t = useTranslations("eventSources");
  const source = useEventSource(sourceId);
  const [token, setToken] = useState<string | null>(null);
  const { listen, capture } = useSourceListener(sourceId, token);
  const consumed = useRef<string | null>(null);
  const caught = capture.data?.state === "caught" ? capture.data.delivery : undefined;
  useEffect(() => {
    if (caught && token !== consumed.current) {
      consumed.current = token;
      onSample(caught);
    }
  }, [caught, token, onSample]);
  const waiting =
    token !== null &&
    capture.data?.state !== "caught" &&
    capture.data?.state !== "expired" &&
    capture.data?.state !== "too_large" &&
    !capture.error;
  return (
    <div className="space-y-3 rounded-md border p-3">
      <p className="text-muted-foreground text-xs">{t("liveWarning")}</p>
      {source.data?.can_use && (
        <>
          <CopyableValue
            id="sample-live-url"
            label={t("liveUrl")}
            value={source.data.webhook_url}
          />
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={listen.isPending || waiting}
            onClick={() =>
              listen.mutate(undefined, { onSuccess: (result) => setToken(result.listener_id) })
            }
          >
            {waiting && <Spinner className="size-3.5" />}
            {waiting ? t("listening") : t("listen")}
          </Button>
        </>
      )}
      {source.data && !source.data.can_use && (
        <p className="text-muted-foreground text-xs">{t("noUse")}</p>
      )}
      {(source.error || listen.error || capture.error) && (
        <p role="alert" className="text-destructive text-xs">
          {t("captureError")}
        </p>
      )}
      {capture.data?.state === "expired" && (
        <p role="status" className="text-muted-foreground text-xs">
          {t("expired")}
        </p>
      )}
      {capture.data?.state === "too_large" && (
        <p role="alert" className="text-destructive text-xs">
          {t("sampleTooLarge", { limit: MAX_PINNED_BYTES })}
        </p>
      )}
      {caught && (
        <p role="status" className="text-sm">
          {t("caught")}
        </p>
      )}
      <PasteSample onSample={onSample} />
    </div>
  );
}

export function PasteSample({ onSample }: { onSample: (sample: EventSample) => void }) {
  const t = useTranslations("eventSources");
  const [draft, setDraft] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const apply = () => {
    let value: unknown;
    try {
      value = JSON.parse(draft);
    } catch {
      setProblem(t("invalidJson"));
      return;
    }
    if (value === null || typeof value !== "object" || Array.isArray(value)) {
      setProblem(t("invalidJson"));
      return;
    }
    if (jsonBytes({ body: value, delivery_id: "example" }) > MAX_PINNED_BYTES) {
      setProblem(t("sampleTooLarge", { limit: MAX_PINNED_BYTES }));
      return;
    }
    setProblem(null);
    onSample({ body: value as Record<string, unknown>, delivery_id: "example" });
  };
  return (
    <details className="space-y-2">
      <summary className="cursor-pointer text-sm">{t("pasteExample")}</summary>
      <Label htmlFor="event-sample-json">{t("exampleJson")}</Label>
      <Textarea
        id="event-sample-json"
        rows={5}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        className="font-mono text-xs"
      />
      {problem && (
        <p role="alert" className="text-destructive text-xs">
          {problem}
        </p>
      )}
      <Button type="button" size="sm" variant="outline" onClick={apply}>
        {t("useExample")}
      </Button>
    </details>
  );
}
