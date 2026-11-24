"use client";

import { useTranslations } from "next-intl";

import type { ToolCall } from "@/types";

/** One secret an agent asked for, as the step shows it. */
export interface RequestedSecret {
  secretName: string;
  whatFor: string;
  kind: string;
}

/**
 * The secret a `request_secret` call asked for, from its arguments.
 *
 * The arguments hold the name and what it is for - never the value, which
 * no tool call ever carries. The result names the stored secret and its
 * hint once fulfilled, or the decline when the person refused. Null when
 * the arguments are not a secret request, so the step falls back to the
 * generic view rather than drawing nothing.
 */
export function parseSecretRequest(toolCall: ToolCall): RequestedSecret | null {
  const args = toolCall.args as { secret_name?: unknown; what_for?: unknown; kind?: unknown };
  if (typeof args?.secret_name !== "string" || args.secret_name.trim() === "") return null;
  if (typeof args?.what_for !== "string" || args.what_for.trim() === "") return null;
  return {
    secretName: args.secret_name.trim(),
    whatFor: args.what_for.trim(),
    kind: typeof args?.kind === "string" && args.kind !== "" ? args.kind : "api_key",
  };
}

/** Whether the call's result says the secret was provided and stored. */
export function secretRequestFulfilled(toolCall: ToolCall): string | null {
  const result = toolCall.result;
  // i18n-exempt: a wire prefix the server writes, matched not rendered.
  if (typeof result !== "string" || !result.startsWith("Secret provided and stored")) return null;
  return result;
}

/** Whether the call's result says the person declined to provide it. */
export function secretRequestDeclined(toolCall: ToolCall): boolean {
  const result = toolCall.result;
  return typeof result === "string" && result.includes("declined to provide this secret");
}

/**
 * What the agent asked for and what happened to it - the name and what it
 * is for, then the stored secret's hint once fulfilled, or that the person
 * declined. The value is never rendered: it is not in the arguments, and
 * the result that carries the fulfilment names only the secret and its hint.
 */
export function SecretRequestResult({
  requested,
  fulfilled,
  declined,
}: {
  requested: RequestedSecret;
  fulfilled: string | null;
  declined: boolean;
}) {
  const t = useTranslations("chat.secretRequest");
  return (
    <div className="space-y-1.5 py-1">
      <p className="text-foreground text-[13px] font-medium">
        <span className="font-mono">{requested.secretName}</span>
      </p>
      <p className="text-muted-foreground text-[13px]">{requested.whatFor}</p>
      {fulfilled !== null ? (
        <p className="text-muted-foreground text-[13px]">{t("provided")}</p>
      ) : declined ? (
        <p className="text-muted-foreground text-[13px]">{t("declined")}</p>
      ) : (
        <p className="text-muted-foreground text-[13px]">{t("waiting")}</p>
      )}
    </div>
  );
}
