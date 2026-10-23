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
  /** What the card says under its title, where that is not the prompt itself; empty for nothing. */
  description?: string;
  /** Offered as a small × on the card - a pinned prompt taken off. */
  onRemove?: () => void;
}

interface ChatWelcomeProps {
  /** Above the title: an icon tile, or the avatar of whoever answers. */
  mark: ReactNode;
  title: string;
  lead: ReactNode;
  suggestions: readonly WelcomeSuggestion[];
  onPick: (prompt: string) => void;
  /** Under the cards: hints, a note. */
  footer?: ReactNode;
  /** Between the lead and the cards: what the platform proposes to this person (#2301). */
  notice?: ReactNode;
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
  notice,
  compact = false,
}: ChatWelcomeProps) {
  const t = useTranslations("chat.empty");
  return (
    // A short window - a laptop zoomed in, a browser half the screen - keeps the
    // greeting and the suggestions and drops the mark, the shortcuts and the
    // air: all of it stacked put the cards under the composer.
    <div
      className={cn(
        "@container mx-auto w-full",
        compact ? "px-3 py-2" : "max-w-2xl px-4 py-6 md:[@media(min-height:761px)]:py-16",
      )}
    >
      <div className="text-center">
        <div
          className={cn(
            "mx-auto flex justify-center",
            compact ? "mb-3" : "mb-5 [@media(max-height:760px)]:hidden",
          )}
        >
          {mark}
        </div>
        <h2
          className={cn(
            "text-foreground font-semibold tracking-tight",
            compact ? "text-lg" : "text-2xl md:text-3xl",
          )}
        >
          {title}
        </h2>
        <p
          className={cn(
            "text-muted-foreground mx-auto line-clamp-2 max-w-md leading-relaxed",
            compact ? "mt-1 text-[13px]" : "mt-2 text-sm",
          )}
        >
          {lead}
        </p>
      </div>

      {notice && <div className={compact ? "mt-3" : "mt-6"}>{notice}</div>}

      <div className={cn("grid", compact ? "mt-4 gap-1.5" : "mt-8 gap-3 sm:grid-cols-2")}>
        {suggestions.map((suggestion) => (
          <div key={suggestion.key} className="relative">
            <button
              type="button"
              onClick={() => onPick(suggestion.prompt)}
              // A filled card rather than a hairline box: four outlines on a
              // blank page read as a form to fill in, not as places to start.
              className={cn(
                "group bg-muted/60 hover:bg-muted focus-visible:ring-ring flex w-full items-start gap-3 rounded-2xl text-left transition-colors outline-none focus-visible:ring-2",
                compact ? "px-3 py-2.5" : "p-3.5 md:p-4",
              )}
            >
              {/* Off in a narrow column, where it took a third of a card's
                  width and wrapped the title onto two lines. */}
              <span className="bg-card text-foreground shadow-card flex h-9 w-9 shrink-0 items-center justify-center rounded-xl @max-xl:hidden">
                <suggestion.icon className="h-4 w-4" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="text-foreground block text-sm font-medium">
                  {suggestion.title}
                </span>
                {suggestion.description !== "" && (
                  <span
                    className={cn(
                      "text-muted-foreground mt-0.5 block text-[13px] leading-relaxed",
                      // A narrow window shows four cards and a composer at once only
                      // when each says its prompt in a line.
                      compact ? "line-clamp-1" : "line-clamp-1 md:line-clamp-2",
                    )}
                  >
                    {suggestion.description ?? suggestion.prompt}
                  </span>
                )}
              </span>
              {suggestion.onRemove ? (
                // Room for the × that sits over this corner.
                <span className="h-4 w-4 shrink-0" />
              ) : (
                <ArrowUpRight className="text-muted-foreground group-hover:text-foreground mt-0.5 h-4 w-4 shrink-0 opacity-0 transition-[opacity,color] group-hover:opacity-100 group-focus-visible:opacity-100" />
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
        // Keyboard hints, so not on a phone - where they also ran into the
        // caption under the composer.
        <div className="text-muted-foreground mt-8 hidden flex-wrap items-center justify-center gap-x-2 gap-y-1 text-xs md:[@media(min-height:761px)]:flex">
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
