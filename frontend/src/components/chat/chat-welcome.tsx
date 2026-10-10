"use client";

import type { ReactNode } from "react";
import { ArrowUpRight, X, type LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";

export interface WelcomeSuggestion {
  key: string;
  icon: LucideIcon;
  title: string;
  /** What is sent when it is picked, shown under the title unless `description` is. */
  prompt: string;
  /** What the card says under its title, where that is not the prompt itself. */
  description?: string;
  /** Offered as a small × on the card - a pinned prompt taken off. */
  onRemove?: () => void;
}

interface ChatWelcomeProps {
  /** Above the title: an icon tile, or the avatar of whoever answers. */
  mark: ReactNode;
  title: string;
  lead: string;
  suggestions: readonly WelcomeSuggestion[];
  onPick: (prompt: string) => void;
  /** Under the cards: hints, a note. */
  footer?: ReactNode;
  /** A narrow window - the Architect's, the Builder's test panel: one column, tighter. */
  compact?: boolean;
}

/**
 * An empty conversation, the way `/chat` draws one (#2075): a mark, a title, a
 * line saying what answers here, and cards that start a conversation.
 *
 * One component so the main chat, the AI Architect's window and the Builder's
 * test panel open on the same page rather than three that drifted apart.
 */
export function ChatWelcome({
  mark,
  title,
  lead,
  suggestions,
  onPick,
  footer,
  compact = false,
}: ChatWelcomeProps) {
  const t = useTranslations("chat.empty");
  return (
    <div className={cn("mx-auto w-full", compact ? "px-4 py-6" : "max-w-2xl px-4 py-12 md:py-16")}>
      <div className="text-center">
        <div className="mx-auto mb-5 flex justify-center">{mark}</div>
        <h2
          className={cn(
            "text-foreground font-semibold tracking-tight",
            compact ? "text-xl" : "text-2xl md:text-3xl",
          )}
        >
          {title}
        </h2>
        <p className="text-muted-foreground mx-auto mt-2 max-w-md text-sm leading-relaxed">
          {lead}
        </p>
      </div>

      <div className={cn("grid", compact ? "mt-5 gap-2" : "mt-8 gap-3 sm:grid-cols-2")}>
        {suggestions.map((suggestion) => (
          <div key={suggestion.key} className="relative">
            <button
              type="button"
              onClick={() => onPick(suggestion.prompt)}
              className={cn(
                "group border-border bg-card hover:border-foreground/30 hover:bg-accent flex w-full items-start gap-3 rounded-xl border text-left transition-colors",
                compact ? "p-3" : "p-4",
              )}
            >
              <span className="bg-muted text-muted-foreground group-hover:text-foreground flex h-9 w-9 shrink-0 items-center justify-center rounded-lg transition-colors">
                <suggestion.icon className="h-4 w-4" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="text-foreground block text-sm font-medium">
                  {suggestion.title}
                </span>
                <span
                  className={cn(
                    "text-muted-foreground mt-0.5 block text-xs leading-relaxed",
                    // A narrow window shows four cards and a composer at once only
                    // when each says its prompt in a line.
                    compact ? "line-clamp-1" : "line-clamp-2",
                  )}
                >
                  {suggestion.description ?? suggestion.prompt}
                </span>
              </span>
              {suggestion.onRemove ? (
                // Room for the × that sits over this corner.
                <span className="h-4 w-4 shrink-0" />
              ) : (
                <ArrowUpRight className="text-muted-foreground group-hover:text-foreground mt-0.5 h-4 w-4 shrink-0 transition-colors" />
              )}
            </button>
            {suggestion.onRemove && (
              <button
                type="button"
                aria-label={t("unpin", { prompt: suggestion.title })}
                onClick={suggestion.onRemove}
                className="text-muted-foreground hover:text-foreground hover:bg-accent absolute top-2.5 right-2.5 rounded-md p-1"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        ))}
      </div>

      {footer && (
        <div className="text-muted-foreground mt-8 flex flex-wrap items-center justify-center gap-x-2 gap-y-1 text-xs">
          {footer}
        </div>
      )}
    </div>
  );
}

/** The icon tile `/chat` puts above its title. */
export function WelcomeIcon({ icon: Icon }: { icon: LucideIcon }) {
  return (
    <span className="bg-muted text-foreground flex h-12 w-12 items-center justify-center rounded-2xl">
      <Icon className="h-5 w-5" />
    </span>
  );
}
