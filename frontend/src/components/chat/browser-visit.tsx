"use client";

import { ArrowUpRight, Globe, Maximize2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { LinkFavicon } from "./link-favicon";

const surface =
  "group border-border/70 bg-background hover:border-foreground/20 hover:bg-muted/40 focus-visible:ring-ring flex w-full max-w-sm min-w-0 flex-col gap-2 rounded-xl border p-3 text-left outline-none transition-colors focus-visible:ring-2";

/** A visited page keeps its identity in the transcript, even after its live view closes. */
export function BrowserVisit({
  url,
  title,
  onOpen,
}: {
  url: string | null;
  title: string | null;
  onOpen?: () => void;
}) {
  const t = useTranslations("chat");
  const host = url ? new URL(url).hostname.replace(/^www\./, "") : null;
  const label = title || (host ? t("browserLineBrowsed", { host }) : t("browserLineBrowsedWeb"));
  const content = (
    <>
      <span className="text-muted-foreground flex min-w-0 items-center gap-2 text-xs">
        {url ? (
          <LinkFavicon key={url} url={url} className="size-5" />
        ) : (
          <Globe className="size-5" aria-hidden />
        )}
        <span className="min-w-0 flex-1 truncate">{host || t("browserHeading")}</span>
        {onOpen ? (
          <Maximize2
            className="size-3.5 shrink-0 opacity-50 transition-opacity group-hover:opacity-100"
            aria-hidden
          />
        ) : url ? (
          <ArrowUpRight
            className="size-3.5 shrink-0 opacity-50 transition-opacity group-hover:opacity-100"
            aria-hidden
          />
        ) : null}
      </span>
      <span className="text-foreground line-clamp-2 text-sm leading-snug font-medium">{label}</span>
    </>
  );
  if (onOpen)
    return (
      <button
        type="button"
        aria-label={label}
        onClick={onOpen}
        className={surface}
        title={t("browserOpenPanel")}
      >
        {content}
      </button>
    );
  if (url)
    return (
      <a
        aria-label={`${t("browserVisitSite")}: ${label}`}
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        className={surface}
        title={t("browserVisitSite")}
      >
        {content}
      </a>
    );
  return <div className={surface}>{content}</div>;
}
