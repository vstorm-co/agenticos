"use client";

import type { ReactNode } from "react";
import { ExternalLink } from "lucide-react";
import { useTranslations } from "next-intl";

import { CatalogCheck } from "@/components/mcp/catalog-check";
import { McpServerIcon } from "@/components/mcp/mcp-server-icon";
import { Card, CardContent } from "@/components/ui";
import { cn } from "@/lib/utils";
import type { McpCatalogEntry } from "@/types/mcp";

interface McpServerCardProps {
  name: string;
  icon: string | null;
  /** What it asks for, or that it came from the registry - beside the name. */
  badge: ReactNode;
  /** The category as a reader sees it. */
  category: string;
  description: string;
  url: string | null;
  docsUrl: string | null;
  /** The catalog entry, for what the last catalog check found. */
  entry: McpCatalogEntry | null;
  /** The left of the action bar: the card's verbs. */
  actions: ReactNode;
  /** The far right of the action bar, after the check. */
  trailing?: ReactNode;
  /** Top right, beside the badge: the Builder's switch. */
  headerAction?: ReactNode;
  /** The Builder's card for a server this agent uses. */
  selected?: boolean;
  /** Clicking the card's body, where the card is more than its controls. */
  onOpen?: () => void;
  dataTour?: string;
}

/**
 * One MCP server, drawn the same on the servers page and in the Builder.
 *
 * The two used to be different shapes of the same thing - a catalog card there,
 * a dense row here - so a server looked like a different object depending on
 * where somebody met it. The caller decides only the verbs: connecting and
 * managing accounts on the servers page, using the server in this agent in the
 * Builder.
 */
export function McpServerCard({
  name,
  icon,
  badge,
  category,
  description,
  url,
  docsUrl,
  entry,
  actions,
  trailing,
  headerAction,
  selected = false,
  onOpen,
  dataTour,
}: McpServerCardProps) {
  const t = useTranslations("mcp");
  return (
    <Card
      role="group"
      aria-label={name}
      className={cn(
        "h-full transition-colors",
        selected && "border-brand bg-brand/5",
        onOpen && "hover:border-foreground/20 cursor-pointer",
      )}
      data-tour={dataTour}
      onClick={
        onOpen &&
        ((event) => {
          // The card's own controls act for themselves; only the rest of it opens.
          if (!(event.target as HTMLElement).closest("button, a, [role=switch]")) onOpen();
        })
      }
    >
      <CardContent className="flex h-full flex-col gap-3 p-4">
        <div className="flex items-start gap-2.5">
          <McpServerIcon icon={icon} name={name} className="mt-0.5 h-6 w-6" />
          <div className="min-w-0 flex-1 space-y-1">
            <div className="flex items-start justify-between gap-2">
              <span className="truncate text-sm font-medium">{name}</span>
              <span className="flex shrink-0 items-center gap-2">
                {badge}
                {headerAction}
              </span>
            </div>
            <p className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
              {category}
            </p>
            <p className="text-muted-foreground line-clamp-2 text-sm">{description}</p>
            {url === null ? (
              // Prose, so it is set as prose. Monospacing this sentence and then
              // truncating it produced "Self-hosted - you supply the…", which
              // reads as a URL that got cut off.
              <p className="text-muted-foreground text-xs">{t("selfHostedYouSupply")}</p>
            ) : (
              // Truncated rather than wrapped: spelled out, the URL is the tallest
              // thing on the card, and the full copy is one click away.
              <p className="text-muted-foreground truncate font-mono text-xs" title={url}>
                {/* A query string may carry a key - never render one. */}
                {`${url.split("?")[0]}${url.includes("?") ? "?…" : ""}`}
              </p>
            )}
            {docsUrl && (
              <a
                href={docsUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-xs underline underline-offset-4"
              >
                {t("documentation")}
                <ExternalLink className="h-3 w-3" />
              </a>
            )}
          </div>
        </div>

        {/* Pushed to the foot, with a rule above it: cards in a row are the same
            height and their descriptions are not, so actions kept under the
            text landed at a different height in every column. `min-w-0` so the
            row shrinks rather than pushing its right end past the card. */}
        <div className="mt-auto">
          <div className="border-border mt-3 flex min-w-0 items-center gap-1.5 border-t pt-3">
            {actions}
            <div className="ml-auto flex min-w-0 items-center gap-2">
              <CatalogCheck entry={entry} />
              {trailing}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
