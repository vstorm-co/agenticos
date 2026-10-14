"use client";

import { ArrowRight, ChevronLeft, ChevronRight, X } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useRef, useState } from "react";

import type { CapabilityArtStyle } from "@/components/agents/capability-art/art.generated";
import {
  CapabilityArt,
  useCapabilityView,
} from "@/components/agents/capability-art/capability-card";
import { BrandIcon, type BrandName } from "@/components/icons/brand-icon";
import { Button, Card, CardContent } from "@/components/ui";
import { SCROLL_FADE, useScrollFade } from "@/components/ui/scroll-fade";
import { usePermissions } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { cn } from "@/lib/utils";
import { Perm, type Permission } from "@/types/permissions";

/** One tip: what it shows, where it leads, and who it is worth showing to. */
interface Tip {
  id: string;
  href: string;
  /** Drawn with the capability's own illustration, so the tip and the Toolbox agree. */
  art?: string;
  /** Or with the marks of the services it is about, in their colours. */
  brands?: readonly { name: BrandName; color: string }[];
  /** Shown only to a reader who can act on it; none is everybody. */
  gate?: Permission;
}

const TIPS: readonly Tip[] = [
  {
    id: "mcp",
    href: ROUTES.SETTINGS_MCP,
    brands: [
      { name: "claude", color: "#D97757" },
      { name: "cursor", color: "currentColor" },
    ],
  },
  { id: "subagents", href: ROUTES.AGENTS, art: "subagents", gate: Perm.agentsEdit },
  { id: "sandbox", href: ROUTES.AGENTS, art: "sandbox", gate: Perm.agentsEdit },
  { id: "apps", href: ROUTES.ARTIFACTS, art: "artifacts", gate: Perm.artifactsView },
  { id: "routines", href: ROUTES.ROUTINES, art: "clock", gate: Perm.agentsEdit },
  {
    id: "channels",
    href: ROUTES.CHANNELS,
    gate: Perm.channelsManage,
    brands: [
      { name: "slack", color: "#4A154B" },
      { name: "telegram", color: "#26A5E4" },
      { name: "mattermost", color: "#0058CC" },
    ],
  },
  { id: "browser", href: ROUTES.AGENTS, art: "browser_use", gate: Perm.agentsEdit },
  { id: "knowledge", href: ROUTES.RAG, art: "knowledge", gate: Perm.agentsEdit },
  { id: "skills", href: ROUTES.SKILLS, art: "skills", gate: Perm.agentsEdit },
];

const DISMISSED_KEY = "agenticos:discover-tips:dismissed";

function readDismissed(): ReadonlySet<string> {
  try {
    const stored: unknown = JSON.parse(window.localStorage.getItem(DISMISSED_KEY) ?? "[]");
    return new Set(Array.isArray(stored) ? stored.filter((id) => typeof id === "string") : []);
  } catch {
    return new Set();
  }
}

/**
 * What the platform can do that a person would not find by looking: its own
 * MCP server, sandboxes, apps, subagents, routines and the rest - one tile each,
 * leading to where it is switched on.
 *
 * On a person's own dashboard, under the start checklist. Each tile closes on
 * its own and the card goes once every tile has; which ones are closed is kept
 * in this browser, as the checklist's closing is. A tip about something the
 * reader cannot use is not offered at all.
 */
export function DiscoverTips() {
  const t = useTranslations("dashboard.discover");
  const { can } = usePermissions();
  const [view] = useCapabilityView();
  const [dismissed, setDismissed] = useState(readDismissed);
  const strip = useRef<HTMLDivElement>(null);
  useScrollFade(strip);

  const tips = TIPS.filter((tip) => !dismissed.has(tip.id) && (!tip.gate || can(tip.gate)));
  if (tips.length === 0) return null;
  // The Toolbox's illustrated style where the reader has picked one, else the
  // isometric one: the list view has no art to borrow.
  const artStyle: CapabilityArtStyle = view === "crew" ? "crew" : "isometric";

  const dismiss = (ids: readonly string[]) => {
    const next = new Set([...dismissed, ...ids]);
    setDismissed(next);
    try {
      window.localStorage.setItem(DISMISSED_KEY, JSON.stringify([...next]));
    } catch {
      // Nowhere to keep it; closed for this visit.
    }
  };
  const page = (direction: 1 | -1) =>
    strip.current?.scrollBy({
      left: direction * strip.current.clientWidth * 0.85,
      behavior: "smooth",
    });

  return (
    <Card className="mt-6">
      <CardContent className="space-y-3 p-5">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <h2 className="text-sm font-semibold">{t("title")}</h2>
            <p className="text-muted-foreground text-xs">{t("subtitle")}</p>
          </div>
          <div className="hidden gap-1 sm:flex">
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              aria-label={t("previous")}
              onClick={() => page(-1)}
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              aria-label={t("next")}
              onClick={() => page(1)}
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            aria-label={t("dismissAll")}
            onClick={() => dismiss(tips.map((tip) => tip.id))}
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
        <div
          ref={strip}
          className={cn(
            "-mx-1 flex snap-x snap-mandatory scrollbar-none gap-3 overflow-x-auto px-1 pb-1",
            SCROLL_FADE,
          )}
        >
          {tips.map((tip) => (
            <TipTile
              key={tip.id}
              tip={tip}
              artStyle={artStyle}
              onDismiss={() => dismiss([tip.id])}
            />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function TipTile({
  tip,
  artStyle,
  onDismiss,
}: {
  tip: Tip;
  artStyle: CapabilityArtStyle;
  onDismiss: () => void;
}) {
  const t = useTranslations("dashboard.discover");
  const title = t(`tips.${tip.id}.title`);
  return (
    <article
      aria-label={title}
      className="group bg-card relative flex w-[72%] shrink-0 snap-start flex-col overflow-hidden rounded-xl border sm:w-60"
    >
      {tip.art ? (
        <CapabilityArt id={tip.art} name={title} artStyle={artStyle} />
      ) : (
        <div className="from-muted to-muted/40 flex aspect-video items-center justify-center gap-3 bg-gradient-to-br">
          {tip.brands?.map((brand) => (
            <span
              key={brand.name}
              className="bg-background grid size-12 place-items-center rounded-2xl shadow-sm"
              style={{ color: brand.color }}
            >
              <BrandIcon name={brand.name} className="size-6" />
            </span>
          ))}
        </div>
      )}
      <button
        type="button"
        onClick={onDismiss}
        aria-label={t("dismiss", { title })}
        className="bg-background/85 text-muted-foreground hover:text-foreground absolute top-2 right-2 grid size-6 place-items-center rounded-full opacity-0 shadow-sm backdrop-blur transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
      >
        <X className="size-3.5" />
      </button>
      <div className="flex flex-1 flex-col gap-1 px-3 py-2.5">
        <h3 className="text-sm font-medium">{title}</h3>
        <p className="text-muted-foreground line-clamp-3 text-xs leading-relaxed">
          {t(`tips.${tip.id}.body`)}
        </p>
        <Link
          href={tip.href}
          className="text-foreground mt-auto flex items-center gap-1 pt-1.5 text-xs font-medium hover:underline"
        >
          {t(`tips.${tip.id}.cta`)}
          <ArrowRight className="size-3" aria-hidden />
        </Link>
      </div>
    </article>
  );
}
