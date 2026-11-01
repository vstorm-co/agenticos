"use client";

import { useCallback, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { getErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import { getWebhookTest, listenForWebhookTest } from "@/lib/workflows/exposures-api";
import type { WebhookTestCapture, WebhookTestListening } from "@/lib/workflows/types";

/** How often an open test URL is asked whether its call has come. */
const POLL_MS = 1000;

/**
 * A draft webhook's test URL: `listen` opens one, and while it waits it is
 * asked every second whether its one call has come. `stop` forgets it - the URL
 * closes on its own two minutes after it opened.
 */
export function useWebhookTest(workflowId: string) {
  const tErrors = useTranslations("errors");
  const [listening, setListening] = useState<WebhookTestListening | null>(null);
  const token = listening?.test_token ?? "";

  const { data } = useQuery({
    queryKey: qk.workflows.webhookTest(workflowId, token),
    queryFn: () => getWebhookTest(workflowId, token),
    enabled: listening !== null,
    refetchInterval: (query) =>
      query.state.data === undefined || query.state.data.state === "listening" ? POLL_MS : false,
  });
  const listen = useMutation({
    mutationFn: () => listenForWebhookTest(workflowId),
    onSuccess: setListening,
    onError: (error: unknown) => toast.error(getErrorMessage(error, tErrors)),
  });
  const stop = useCallback(() => setListening(null), []);
  const capture: WebhookTestCapture | null = listening === null ? null : (data ?? null);
  return { listening, capture, listen, stop };
}
