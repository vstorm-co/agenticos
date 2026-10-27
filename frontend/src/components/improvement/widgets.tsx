"use client";

import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import {
  ArrowDownRight,
  ArrowUpRight,
  CheckCircle2,
  ChevronRight,
  Circle,
  CircleDashed,
  Loader2,
  Minus,
  XCircle,
} from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import type { FigureTone } from "@/components/ui/figure";
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

const TONE_INK: Record<FigureTone, string> = {
  indigo: "var(--series-1)",
  teal: "var(--series-2)",
  amber: "var(--series-3)",
  rose: "var(--series-4)",
  violet: "var(--series-5)",
};

/**
 * A row of figures a step leads with, two across on a phone. Drawn like the
 * dashboard's figures, except that a label wraps: a phone tile is too narrow for
 * "Answers rated down" on one line, and a cut label is a number nobody can name.
 */
export function Tiles({ tiles, label }: { tiles: Tile[]; label?: string }) {
  return (
    <div
      role="group"
      aria-label={label}
      className={cn(
        "grid grid-cols-2 gap-3",
        tiles.length >= 4 ? "lg:grid-cols-4" : tiles.length === 3 && "sm:grid-cols-3",
      )}
    >
      {tiles.map(({ label: name, value, unit, caption, tone, icon: Icon, href }) => {
        const Box = href ? "a" : "div";
        return (
          <Box
            key={name}
            href={href}
            className={cn(
              "bg-card flex min-w-0 flex-col rounded-xl border p-3 sm:p-4",
              href && "hover:bg-muted/50 focus-visible:ring-ring focus-visible:ring-2",
            )}
          >
            <div className="flex items-start justify-between gap-2">
              <p className="text-muted-foreground flex min-w-0 items-start gap-1.5 text-xs leading-snug tracking-wide uppercase">
                {tone && (
                  <span
                    aria-hidden
                    className="mt-1 size-2 shrink-0 rounded-full"
                    style={{ background: TONE_INK[tone] }}
                  />
                )}
                <span className="break-words">{name}</span>
              </p>
              {Icon && <Icon className="text-muted-foreground size-4 shrink-0" aria-hidden />}
            </div>
            <p className="mt-auto flex flex-wrap items-baseline gap-x-2 pt-1">
              <span className="text-2xl font-semibold tracking-tight">{value}</span>
              {unit && <span className="text-muted-foreground text-xs">{unit}</span>}
            </p>
            {caption && <p className="text-muted-foreground mt-1 text-xs">{caption}</p>}
          </Box>
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
  good: "text-success",
  bad: "text-destructive",
  warn: "text-warning",
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
}: {
  before: number;
  after: number;
  total: number;
  label: string;
  title: string;
}) {
  const t = useTranslations("improvement");
  const locale = useLocale();
  const delta = after - before;
  const Arrow = delta === 0 ? Minus : delta > 0 ? ArrowUpRight : ArrowDownRight;
  const share = (value: number) => `${(value / Math.max(1, total)) * 100}%`;
  return (
    <figure className="space-y-2 rounded-xl border p-4">
      <figcaption className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-sm font-medium">{title}</span>
        <span
          className={cn(
            "inline-flex items-center gap-0.5 text-sm font-semibold tabular-nums",
            delta === 0 ? "text-muted-foreground" : delta > 0 ? "text-success" : "text-destructive",
          )}
        >
          <Arrow className="size-4" aria-hidden />
          {new Intl.NumberFormat(locale, { signDisplay: "exceptZero" }).format(delta)}
        </span>
      </figcaption>
      <div role="img" aria-label={label} className="space-y-1.5">
        {[
          { key: "before", name: t("before"), value: before, fill: "bg-muted-foreground/50" },
          {
            key: "after",
            name: t("after"),
            value: after,
            fill: delta < 0 ? "bg-destructive" : "bg-success",
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
                  ? "text-success"
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
}: {
  summary: ReactNode;
  children: ReactNode;
  className?: string;
  onToggle?: (open: boolean) => void;
  tour?: string;
}) {
  return (
    <details
      className={cn("group rounded-xl border", className)}
      data-tour={tour}
      onToggle={onToggle && ((event) => onToggle(event.currentTarget.open))}
    >
      {/* The browser's own marker sits on a line of its own above a block summary,
          so the arrow is drawn here, in the same row as what it opens. */}
      <summary className="hover:bg-muted/50 flex cursor-pointer list-none items-start gap-2 rounded-xl px-4 py-3 text-sm font-medium [&::-webkit-details-marker]:hidden">
        <ChevronRight
          aria-hidden
          className="text-muted-foreground mt-0.5 size-4 shrink-0 transition-transform group-open:rotate-90"
        />
        <span className="min-w-0 flex-1">{summary}</span>
      </summary>
      <div className="space-y-4 px-4 pb-4">{children}</div>
    </details>
  );
}
