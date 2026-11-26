"use client";

import { NativeDisclosure } from "@/components/ui/native-disclosure";

import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import {
  CheckCircle2,
  ChevronRight,
  Circle,
  CircleDashed,
  Loader2,
  Minus,
  XCircle,
} from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { DeltaChip, FigureCard, type FigureTone } from "@/components/ui/figure";
import { cn } from "@/lib/utils";

export interface Tile {
  label: string;
  value: ReactNode;
  unit?: string;
  caption?: ReactNode;
  tone?: FigureTone;
  icon?: LucideIcon;
  /** Where the figure is listed in full, on the same page. */
  href?: string;
}

/**
 * A row of figures a step leads with, stacked on the narrowest phones: the dashboard's
 * `FigureCard`, with a label that wraps, and a link to where a figure is listed in full.
 */
export function Tiles({
  tiles,
  label,
  compact = false,
}: {
  tiles: Tile[];
  label?: string;
  compact?: boolean;
}) {
  if (compact)
    return (
      <dl
        role="group"
        aria-label={label}
        className="grid grid-cols-2 gap-x-6 gap-y-4 sm:flex sm:flex-wrap sm:gap-8"
      >
        {tiles.map((tile) => (
          <div key={tile.label} className="min-w-0 space-y-1">
            <dt className="text-muted-foreground text-xs">{tile.label}</dt>
            <dd className="text-xl font-medium tabular-nums">
              {tile.href ? (
                <a className="underline underline-offset-4" href={tile.href}>
                  {tile.value}
                </a>
              ) : (
                tile.value
              )}
            </dd>
            {tile.caption && (
              <dd className="text-muted-foreground max-w-64 text-xs">{tile.caption}</dd>
            )}
          </div>
        ))}
      </dl>
    );
  return (
    <div
      role="group"
      aria-label={label}
      className={cn(
        "grid grid-cols-1 gap-3 min-[380px]:grid-cols-2",
        tiles.length >= 4 ? "lg:grid-cols-4" : tiles.length === 3 && "sm:grid-cols-3",
      )}
    >
      {tiles.map(({ label: name, href, ...figure }) => {
        const card = (
          <FigureCard
            {...figure}
            label={name}
            wrapLabel
            className={cn("h-full min-w-0", href && "hover:bg-muted/50 transition-colors")}
          />
        );
        return href ? (
          <a
            key={name}
            href={href}
            className="focus-visible:ring-ring min-w-0 rounded-2xl focus-visible:ring-2 focus-visible:outline-none"
          >
            {card}
          </a>
        ) : (
          <div key={name} className="min-w-0">
            {card}
          </div>
        );
      })}
    </div>
  );
}

export type Tone = "good" | "bad" | "warn" | "neutral";

const CHIP: Record<Tone, string> = {
  good: "border-success/30 bg-success/10",
  bad: "border-destructive/35 bg-destructive/10",
  warn: "border-warning/35 bg-warning/10",
  neutral: "border-border bg-muted text-muted-foreground",
};

const INK: Record<Tone, string> = {
  good: "text-success-ink",
  bad: "text-destructive-ink",
  warn: "text-warning-ink",
  neutral: "text-muted-foreground",
};

const MARK: Record<Tone, LucideIcon> = {
  good: CheckCircle2,
  bad: XCircle,
  warn: CircleDashed,
  neutral: Minus,
};

/** A state said with an icon and a word as well as a colour. */
export function StateBadge({
  tone,
  children,
  className,
}: {
  tone: Tone;
  children: ReactNode;
  className?: string;
}) {
  const Icon = MARK[tone];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium",
        CHIP[tone],
        className,
      )}
    >
      <Icon className={cn("size-3.5 shrink-0", INK[tone])} aria-hidden />
      {children}
    </span>
  );
}

interface Part {
  label: string;
  value: number;
  /** A `var(--…)` colour or a Tailwind background class. */
  fill: string;
  icon?: LucideIcon;
  ink?: string;
}

/**
 * One bar split into the parts that make up a whole, and a key that prints each
 * part's count, so colour is never the only thing carrying a number. The bar is
 * an image named by `label`, which is the sentence it draws.
 */
export function Proportion({
  parts,
  label,
  className,
}: {
  parts: Part[];
  label: string;
  className?: string;
}) {
  const locale = useLocale();
  const total = parts.reduce((sum, part) => sum + part.value, 0);
  return (
    <div className={cn("@container space-y-3", className)}>
      <div
        role="img"
        aria-label={label}
        className="bg-muted flex h-3 gap-[3px] overflow-hidden rounded-full"
      >
        {parts
          .filter((part) => part.value > 0)
          .map((part) => (
            <span
              key={part.label}
              className={cn(
                "h-full first:rounded-l-full last:rounded-r-full",
                fillClass(part.fill),
              )}
              style={{
                width: `${Math.max(2, (part.value / total) * 100)}%`,
                ...fillStyle(part.fill),
              }}
            />
          ))}
      </div>
      <ul className="grid gap-x-6 gap-y-1.5 @[30rem]:grid-cols-2">
        {parts.map((part) => {
          const Icon = part.icon;
          return (
            <li
              key={part.label}
              className={cn("flex items-center gap-2 text-sm", part.value === 0 && "opacity-50")}
            >
              {Icon ? (
                <Icon className={cn("size-4 shrink-0", part.ink)} aria-hidden />
              ) : (
                <span
                  aria-hidden
                  className={cn("size-2.5 shrink-0 rounded-[3px]", fillClass(part.fill))}
                  style={fillStyle(part.fill)}
                />
              )}
              <span className="text-muted-foreground min-w-0 flex-1">{part.label}</span>
              <span className="font-medium tabular-nums">{part.value.toLocaleString(locale)}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function fillClass(fill: string) {
  return fill.startsWith("var(") ? undefined : fill;
}

function fillStyle(fill: string) {
  return fill.startsWith("var(") ? { background: fill } : undefined;
}

/**
 * Handled well before and after, as two bars against the same total and the
 * difference beside them. The whole is an image named by `label`, the sentence
 * that says the same numbers.
 */
export function BeforeAfter({
  before,
  after,
  total,
  label,
  title,
  tone,
}: {
  before: number;
  after: number;
  total: number;
  label: string;
  title: string;
  /** How the change reads; by default its direction, and neutral when unchanged. */
  tone?: "good" | "bad" | "neutral";
}) {
  const t = useTranslations("improvement");
  const delta = after - before;
  const reads = tone ?? (delta === 0 ? "neutral" : delta > 0 ? "good" : "bad");
  const share = (value: number) => `${(value / Math.max(1, total)) * 100}%`;
  return (
    <figure className="space-y-2 rounded-xl border p-4">
      <figcaption className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-sm font-medium">{title}</span>
        <DeltaChip
          delta={delta}
          percent={false}
          // The chip paints a rise as good or bad; a fall that reads well is a rise that would not.
          rising={
            reads === "neutral" ? "neutral" : (reads === "good") === delta > 0 ? "good" : "bad"
          }
        />
      </figcaption>
      <div role="img" aria-label={label} className="space-y-1.5">
        {[
          { key: "before", name: t("before"), value: before, fill: "bg-muted-foreground/50" },
          {
            key: "after",
            name: t("after"),
            value: after,
            fill:
              reads === "neutral"
                ? "bg-muted-foreground/50"
                : reads === "bad"
                  ? "bg-destructive"
                  : "bg-success",
          },
        ].map((row) => (
          <div key={row.key} className="flex items-center gap-3 text-xs">
            <span className="text-muted-foreground w-14 shrink-0">{row.name}</span>
            <span className="bg-muted h-2.5 flex-1 overflow-hidden rounded-full">
              <span
                className={cn("block h-full rounded-full", row.fill)}
                style={{ width: share(row.value) }}
              />
            </span>
            <span className="w-16 shrink-0 text-right tabular-nums">
              {t("widgets.ofTotal", { count: row.value, total })}
            </span>
          </div>
        ))}
      </div>
    </figure>
  );
}

export type StageState = "done" | "running" | "pending";

const STAGE_ICON: Record<StageState, LucideIcon> = {
  done: CheckCircle2,
  running: Loader2,
  pending: Circle,
};

/** Stages in order, each with an icon and a word for its state - across on a wide screen. */
export function Stepper({
  stages,
  label,
}: {
  stages: { id: string; label: string; state: StageState; stateLabel: string }[];
  label: string;
}) {
  return (
    <ol aria-label={label} className="grid gap-3 sm:auto-cols-fr sm:grid-flow-col">
      {stages.map((stage) => {
        const Icon = STAGE_ICON[stage.state];
        return (
          <li
            key={stage.id}
            aria-current={stage.state === "running" ? "step" : undefined}
            className={cn(
              "flex items-start gap-3 rounded-xl border p-3",
              stage.state === "running" && "border-chart/50 bg-chart/5",
            )}
          >
            <Icon
              aria-hidden
              className={cn(
                "mt-0.5 size-5 shrink-0",
                stage.state === "done"
                  ? "text-success-ink"
                  : stage.state === "running"
                    ? "text-chart animate-spin"
                    : "text-muted-foreground",
              )}
            />
            <span className="min-w-0 space-y-0.5">
              <span className={cn("block text-sm", stage.state === "running" && "font-medium")}>
                {stage.label}
              </span>
              <span className="text-muted-foreground block text-xs">{stage.stateLabel}</span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}

/** What a step keeps out of its main view until asked for. */
export function Details({
  summary,
  children,
  className,
  onToggle,
  tour,
  initiallyOpen,
  row = false,
}: {
  row?: boolean;
  initiallyOpen?: boolean;
  summary: ReactNode;
  children: ReactNode;
  className?: string;
  onToggle?: (open: boolean) => void;
  tour?: string;
}) {
  return (
    <NativeDisclosure
      className={cn("group", !row && "rounded-xl border", className)}
      data-tour={tour}
      open={initiallyOpen}
      onToggle={onToggle && ((event) => onToggle(event.currentTarget.open))}
    >
      {/* The browser's own marker sits on a line of its own above a block summary,
          so the arrow is drawn here, in the same row as what it opens. */}
      <summary
        className={cn(
          "hover:bg-muted/50 flex cursor-pointer list-none items-start gap-2 py-3 text-sm font-medium [&::-webkit-details-marker]:hidden",
          row ? "rounded-lg px-2" : "rounded-xl px-4",
        )}
      >
        <ChevronRight
          aria-hidden
          className="text-muted-foreground mt-0.5 size-4 shrink-0 transition-transform group-open:rotate-90"
        />
        <span className="min-w-0 flex-1">{summary}</span>
      </summary>
      <div className={cn("space-y-4 pb-4", row ? "px-2" : "px-4")}>{children}</div>
    </NativeDisclosure>
  );
}
