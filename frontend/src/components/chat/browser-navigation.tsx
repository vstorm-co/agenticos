"use client";

import { useState } from "react";
import { ArrowLeft, ArrowRight, CornerDownLeft, RotateCw } from "lucide-react";
import { useTranslations } from "next-intl";

import type { BrowserCommand } from "@/hooks/use-live-browse";

function websiteAddress(value: string): string | null {
  try {
    const hostWithPort = /^(?:localhost|[^:/?#]+\.[^:/?#]+):\d+(?:[/?#]|$)/i.test(value);
    const hasScheme = /^[a-z][a-z\d+.-]*:/i.test(value) && !hostWithPort;
    const target = new URL(hasScheme ? value : `https://${value}`);
    if (
      !["http:", "https:"].includes(target.protocol) ||
      target.username ||
      target.password ||
      target.port === "0"
    )
      return null;
    return target.href;
  } catch {
    return null;
  }
}

/** Navigation drives the held remote tab, never the console's own location. */
export function BrowserNavigation({
  url,
  holding,
  send,
}: {
  url: string | null;
  holding: boolean;
  send: (command: BrowserCommand) => void;
}) {
  const t = useTranslations("browse");
  const [draft, setDraft] = useState<string | null>(null);
  const [invalid, setInvalid] = useState(false);
  return (
    <form
      className="flex min-w-0 flex-1 basis-full items-center gap-1 md:basis-auto"
      title={!holding ? t("browserNavigationHint") : undefined}
      onSubmit={(event) => {
        event.preventDefault();
        if (!holding) return;
        const value = (draft ?? url ?? "").trim();
        const target = websiteAddress(value);
        if (target === null) {
          setInvalid(true);
          return;
        }
        send({ type: "navigate", url: target });
        setDraft(null);
        setInvalid(false);
      }}
    >
      {(
        [
          ["back", ArrowLeft, "browserBack"],
          ["forward", ArrowRight, "browserForward"],
          ["reload", RotateCw, "browserReload"],
        ] as const
      ).map(([type, Icon, label]) => (
        <button
          key={type}
          type="button"
          aria-label={t(label)}
          title={t(label)}
          disabled={!holding}
          className="hover:bg-muted flex size-8 shrink-0 items-center justify-center rounded-lg disabled:opacity-40"
          onClick={() => send({ type })}
        >
          <Icon className="size-4" aria-hidden />
        </button>
      ))}
      <input
        aria-label={t("browserAddress")}
        aria-invalid={invalid}
        title={invalid ? t("browserInvalidAddress") : undefined}
        type="text"
        inputMode="url"
        autoComplete="off"
        spellCheck={false}
        readOnly={!holding}
        className="bg-muted/80 h-8 min-w-0 flex-1 rounded-lg px-2.5 text-sm"
        value={holding ? (draft ?? url ?? "") : (url ?? "")}
        onChange={(event) => {
          setDraft(event.target.value);
          setInvalid(false);
        }}
      />
      {holding && (
        <button
          type="submit"
          aria-label={t("browserGo")}
          title={t("browserGo")}
          className="hover:bg-muted flex size-8 shrink-0 items-center justify-center rounded-lg"
        >
          <CornerDownLeft className="size-4" aria-hidden />
        </button>
      )}
      {invalid && (
        <span role="alert" className="sr-only">
          {t("browserInvalidAddress")}
        </span>
      )}
    </form>
  );
}
