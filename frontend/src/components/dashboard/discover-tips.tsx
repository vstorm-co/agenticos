"use client";

import { ArrowRight, ChevronLeft, ChevronRight, X } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";

import { CapabilityArt } from "@/components/agents/capability-art/capability-card";
import { BrandIcon, type BrandName } from "@/components/icons/brand-icon";
import { Button, Card, CardContent } from "@/components/ui";
import { SCROLL_FADE, useScrollFade } from "@/components/ui/scroll-fade";
import { usePermissions } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { prefersReducedMotion } from "@/lib/motion";
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
  /** Or with the key that opens it, for a tip about typing in the chat. */
  key?: string;
  /** Shown only to a reader who can act on it; none is everybody. */
  gate?: Permission;
}

const TIPS: readonly Tip[] = [
  { id: "sandbox", href: ROUTES.AGENTS, art: "sandbox", gate: Perm.agentsEdit },
  { id: "subagents", href: ROUTES.AGENTS, art: "subagents", gate: Perm.agentsEdit },
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
      { name: "microsoftteams", color: "#6264A7" },
    ],
  },
  { id: "browser", href: ROUTES.AGENTS, art: "browser_use", gate: Perm.agentsEdit },
  { id: "knowledge", href: ROUTES.RAG, art: "knowledge", gate: Perm.agentsEdit },
  { id: "skills", href: ROUTES.SKILLS, art: "skills", gate: Perm.agentsEdit },
  // Keyboard tips remain available after the illustrated product examples.
  { id: "mentions", href: ROUTES.CHAT, key: "@" },
  { id: "commands", href: ROUTES.CHAT, key: "/" },
  {
    id: "mcp",
    href: ROUTES.SETTINGS_MCP,
    brands: [
      { name: "claude", color: "#D97757" },
      { name: "cursor", color: "currentColor" },
    ],
  },
];

const DISMISSED_KEY = "agenticos:discover-tips:dismissed";

/** The strip's `gap-3`: the lit tile is scrolled to just past the one before it. */
const TILE_GAP_PX = 12;

/** How long a tile stays in front before the strip moves on to the next. */
export const ADVANCE_MS = 5000;

function readDismissed(): ReadonlySet<string> {
  try {
    const stored: unknown = JSON.parse(window.localStorage.getItem(DISMISSED_KEY) ?? "[]");
    return new Set(Array.isArray(stored) ? stored.filter((id) => typeof id === "string") : []);
  } catch {
    return new Set();
  }
}

/**
 * What the platform can do that a person would not find by looking: `@` and `/`
 * in the chat, its own MCP server, sandboxes, apps, subagents, routines and the
 * rest - one tile each, leading to where it is switched on.
 *
 * On a person's own dashboard, under the start checklist. Each tile closes on
 * its own and the card goes once every tile has; which ones are closed is kept
 * in this browser, as the checklist's closing is. A tip about something the
 * reader cannot use is not offered at all. The strip moves on by itself, a
 * tile every few seconds, and holds still while the reader is on it.
 */
export function DiscoverTips() {
  const t = useTranslations("dashboard.discover");
  const { can } = usePermissions();
  const [dismissed, setDismissed] = useState(readDismissed);
  const strip = useRef<HTMLDivElement>(null);
  useScrollFade(strip);
  // Held while the reader is on the strip: a tile moving out from under the
  // pointer, or from under the focus, is a tile they cannot read or close.
  const [held, setHeld] = useState(false);

  const tips = TIPS.filter((tip) => !dismissed.has(tip.id) && (!tip.gate || can(tip.gate)));

  // One tile in front at a time: lit, and scrolled into view, then the next,
  // and back to the first after the last - so every tip is seen without anyone
  // reaching for the arrows. Still for reduced motion.
  const [active, setActive] = useState(0);
  useEffect(() => {
    if (held || tips.length === 0 || prefersReducedMotion()) return;
    const timer = window.setInterval(() => {
      setActive((current) => {
        const next = (current + 1) % tips.length;
        // Mounted whenever there is a tip to light, and one tile per tip.
        const node = strip.current!;
        const tile = node.children[next]!;
        const left =
          next === 0
            ? 0
            : node.scrollLeft +
              tile.getBoundingClientRect().left -
              node.getBoundingClientRect().left -
              TILE_GAP_PX;
        node.scrollTo({ left, behavior: "smooth" });
        return next;
      });
    }, ADVANCE_MS);
    return () => window.clearInterval(timer);
  }, [held, tips.length]);

  if (tips.length === 0) return null;

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
          onMouseEnter={() => setHeld(true)}
          onMouseLeave={() => setHeld(false)}
          onFocus={() => setHeld(true)}
          onBlur={() => setHeld(false)}
          className={cn(
            "-mx-1 flex snap-x snap-mandatory scrollbar-none gap-3 overflow-x-auto px-1 pt-1 pb-1.5",
            SCROLL_FADE,
          )}
        >
          {tips.map((tip, index) => (
            <TipTile
              key={tip.id}
              tip={tip}
              lit={index === active % tips.length}
              onDismiss={() => dismiss([tip.id])}
            />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function TipTile({ tip, lit, onDismiss }: { tip: Tip; lit: boolean; onDismiss: () => void }) {
  const t = useTranslations("dashboard.discover");
  const title = t(`tips.${tip.id}.title`);
  return (
    <article
      aria-label={title}
      data-lit={lit || undefined}
      className={cn(
        "group bg-card relative flex w-[72%] shrink-0 snap-start flex-col overflow-hidden rounded-xl border transition-all duration-500 sm:w-60",
        lit
          ? "border-foreground/25 ring-foreground/10 -translate-y-0.5 shadow-md ring-2"
          : "opacity-80 hover:opacity-100",
      )}
    >
      {tip.art ? (
        <CapabilityArt id={tip.art} name={title} />
      ) : tip.key ? (
        <div className="from-muted to-muted/40 flex aspect-video items-center justify-center bg-gradient-to-br">
          <kbd className="bg-background text-foreground grid size-14 place-items-center rounded-2xl font-mono text-2xl font-semibold shadow-sm">
            {tip.key}
          </kbd>
        </div>
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
