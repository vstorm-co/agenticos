"use client";

import { useEffect } from "react";
import { Radio } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button, Spinner } from "@/components/ui";
import { CopyableValue } from "@/components/workflows/triggers/copyable-value";
import { useWebhookTest } from "@/hooks";

/**
 * **Listen for test event** on a webhook trigger: a test URL for the draft,
 * and the one call sent to it handed to `onCaught` - which the output pane
 * pins, so every step after the trigger can be tested against a real delivery.
 * The call starts no run.
 */
export function WebhookListener({
  workflowId,
  onCaught,
}: {
  workflowId: string;
  onCaught: (delivery: Record<string, unknown>) => void;
}) {
  const t = useTranslations("workflows");
  const { listening, capture, listen, stop } = useWebhookTest(workflowId);
  const caught = capture?.state === "caught" ? capture.delivery : null;

  useEffect(() => {
    if (caught === null) return;
    onCaught(caught);
    stop();
  }, [caught, onCaught, stop]);

  if (listening === null || capture?.state === "expired") {
    return (
      <div className="space-y-1.5">
        {capture?.state === "expired" && (
          <p className="text-muted-foreground text-xs">{t("webhookTestExpired")}</p>
        )}
        <Button
          size="sm"
          variant="outline"
          disabled={listen.isPending}
          onClick={() => listen.mutate()}
        >
          <Radio className="size-3.5" />
          {t("webhookTestListen")}
        </Button>
      </div>
    );
  }
  return (
    <div className="border-border space-y-2 rounded-lg border px-3 py-2.5">
      <p className="flex items-center gap-2 text-sm font-medium">
        <Spinner className="size-3.5" />
        {t("webhookTestWaiting")}
      </p>
      <CopyableValue id="webhook-test-url" label={t("webhookTestUrl")} value={listening.url} />
      <p className="text-muted-foreground text-xs">{t("webhookTestHint")}</p>
      <Button size="sm" variant="ghost" onClick={stop}>
        {t("webhookTestStop")}
      </Button>
    </div>
  );
}
