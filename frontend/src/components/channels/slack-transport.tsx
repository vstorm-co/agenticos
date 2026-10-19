"use client";

import { ArrowDownToLine, ArrowUpFromLine } from "lucide-react";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";

/**
 * Which way a Slack bot's connection runs (#2084).
 *
 * Slack either calls this deployment's public address with every message, or
 * the deployment connects out to Slack and receives them over that connection -
 * Socket Mode, which needs no public address and suits a deployment behind a
 * firewall. Each needs its own credential, so the choice decides which field the
 * form asks for.
 */
export function SlackTransport({
  webhookMode,
  onChange,
}: {
  webhookMode: boolean;
  onChange: (webhookMode: boolean) => void;
}) {
  const t = useTranslations("pages.channels");
  const options = [
    {
      webhook: true,
      icon: ArrowDownToLine,
      label: t("slackCallsUs"),
      hint: t("slackCallsUsHint"),
    },
    {
      webhook: false,
      icon: ArrowUpFromLine,
      label: t("weConnectToSlack"),
      hint: t("weConnectToSlackHint"),
    },
  ];
  return (
    <div className="space-y-2">
      <p id="slack-transport" className="text-sm leading-none font-medium">
        {t("slackTransport")}
      </p>
      <div
        role="radiogroup"
        aria-labelledby="slack-transport"
        className="grid gap-2 sm:grid-cols-2"
      >
        {options.map((option) => (
          <button
            key={String(option.webhook)}
            type="button"
            role="radio"
            aria-checked={webhookMode === option.webhook}
            onClick={() => onChange(option.webhook)}
            className={cn(
              "flex flex-col items-start gap-1 rounded-lg border p-3 text-left transition-colors",
              webhookMode === option.webhook
                ? "border-foreground/40 bg-accent"
                : "hover:bg-accent/50",
            )}
          >
            <span className="flex items-center gap-1.5 text-sm font-medium">
              <option.icon className="h-4 w-4" aria-hidden />
              {option.label}
            </span>
            <span className="text-muted-foreground text-xs">{option.hint}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
