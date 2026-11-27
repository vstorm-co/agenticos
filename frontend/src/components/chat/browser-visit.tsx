"use client";

import { ArrowUpRight, Globe, Maximize2, Minimize2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { LinkFavicon } from "./link-favicon";

const surface =
  "group text-muted-foreground hover:text-foreground hover:bg-muted/40 focus-visible:ring-ring touch:min-h-11 inline-flex w-fit max-w-full min-w-0 items-center gap-2 rounded-lg px-2 py-1.5 text-left text-xs outline-none transition-colors focus-visible:ring-2";

/** A visited page keeps its identity in the transcript, even after its live view closes. */
export function BrowserVisit({
  url,
  title,
  onOpen,
  expanded,
}: {
  url: string | null;
  title: string | null;
  onOpen?: () => void;
  expanded?: boolean;
}) {
  const t = useTranslations("chat");
  const host = url ? new URL(url).hostname.replace(/^www\./, "") : null;
  const label = title || (host ? t("browserLineBrowsed", { host }) : t("browserLineBrowsedWeb"));
  const PanelIcon = expanded ? Minimize2 : Maximize2;
  const content = (
    <>
      {url ? (
        <LinkFavicon key={url} url={url} className="size-4 shrink-0" />
      ) : (
        <Globe className="size-4 shrink-0" aria-hidden />
      )}
      <span className="min-w-0 truncate font-medium">{label}</span>
      {title && host && title !== host && <span className="hidden truncate sm:inline">{host}</span>}
      {onOpen ? (
        <PanelIcon
          className="size-3.5 shrink-0 opacity-50 transition-opacity group-hover:opacity-100"
          aria-hidden
        />
      ) : url ? (
        <ArrowUpRight
          className="size-3.5 shrink-0 opacity-50 transition-opacity group-hover:opacity-100"
          aria-hidden
        />
      ) : null}
    </>
  );
  if (onOpen)
    return (
      <button
        type="button"
        aria-label={label}
        onClick={onOpen}
        aria-expanded={expanded}
        className={surface}
        title={t(expanded ? "browserClose" : "browserOpenPanel")}
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
