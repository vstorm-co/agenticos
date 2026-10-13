"use client";

import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { Check, Pencil } from "lucide-react";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";

export interface QuestionChoice {
  label: string;
  description?: string | null;
}

export interface QuestionPromptItem {
  question: string;
  /** A short label for the question, shown as a chip above it. */
  header?: string | null;
  options?: QuestionChoice[];
  /** Whether several options may be picked. */
  multiSelect?: boolean;
  /** Allow a free-form answer via the "Something else" field (default true). */
  allowCustom?: boolean;
}

export interface QuestionPromptAnswer {
  /** Typed text, when the person wrote their own answer. */
  answer: string;
  /** The labels picked, when they chose from the options. */
  selected?: string[];
  skipped: boolean;
}

interface QuestionSlideProps {
  item: QuestionPromptItem;
  /** What was answered before, when the person comes back to this slide. */
  previous: QuestionPromptAnswer | undefined;
  disabled: boolean;
  /** Called with the answer for this slide; the carousel moves on. */
  onAnswer: (answer: QuestionPromptAnswer) => void;
  /** Drawn level with the question, at its right - the close button of a lone question. */
  aside?: ReactNode;
  /** Drawn at the right of the slide's last row - the prompt's Skip. */
  trailing?: ReactNode;
}

/**
 * One question of the carousel. A single-choice pick answers at once; a
 * multi-choice question collects ticks until Continue. Digits pick an option,
 * the arrows move between them and Enter chooses the focused one.
 */
export function QuestionSlide({
  item,
  previous,
  disabled,
  onAnswer,
  aside,
  trailing,
}: QuestionSlideProps) {
  const t = useTranslations("ui");
  const options = item.options ?? [];
  const allowCustom = item.allowCustom ?? true;
  const multi = item.multiSelect ?? false;
  const [focusIdx, setFocusIdx] = useState(0);
  const [picked, setPicked] = useState<string[]>(previous?.selected ?? []);
  const [customOpen, setCustomOpen] = useState(
    allowCustom && (options.length === 0 || !!previous?.answer),
  );
  const [customText, setCustomText] = useState(previous?.answer ?? "");
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (customOpen) inputRef.current?.focus();
    else containerRef.current?.focus();
  }, [customOpen]);

  const choose = (label: string) => {
    if (!multi) {
      onAnswer({ answer: "", selected: [label], skipped: false });
      return;
    }
    setPicked((current) =>
      current.includes(label) ? current.filter((one) => one !== label) : [...current, label],
    );
  };

  const submitCustom = () => {
    const text = customText.trim();
    if (text) onAnswer({ answer: text, skipped: false });
  };

  const onListKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (disabled || customOpen || options.length === 0) return;
    if (/^[1-9]$/.test(event.key)) {
      const option = options[Number(event.key) - 1];
      if (option) {
        event.preventDefault();
        choose(option.label);
      }
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setFocusIdx((index) => Math.min(index + 1, options.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setFocusIdx((index) => Math.max(index - 1, 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      choose(options[focusIdx]!.label);
    }
  };

  return (
    <div
      ref={containerRef}
      tabIndex={-1}
      onKeyDown={onListKeyDown}
      role="group"
      aria-label={t("questionFromAssistant")}
      className="outline-none"
    >
      <div className={cn("flex items-start gap-3 px-3.5 pb-2", aside && "pt-3")}>
        <div className="min-w-0 flex-1 space-y-1">
          {item.header && (
            <span className="text-muted-foreground block text-[11px] font-medium tracking-wide uppercase">
              {item.header}
            </span>
          )}
          <p className="text-foreground text-sm leading-snug font-medium">{item.question}</p>
          {multi && <p className="text-muted-foreground text-xs">{t("pickAnyNumber")}</p>}
        </div>
        {aside}
      </div>

      {options.length > 0 && (
        // Short rows in a list that scrolls on its own: six options with a
        // sentence each used to take half the window and push the composer down.
        <ul className="max-h-[min(40vh,16rem)] space-y-px overflow-y-auto px-1.5 pb-1">
          {options.map((option, index) => {
            const focused = index === focusIdx && !customOpen;
            const ticked = picked.includes(option.label);
            return (
              <li key={option.label}>
                <button
                  type="button"
                  disabled={disabled}
                  aria-pressed={multi ? ticked : undefined}
                  onMouseEnter={() => setFocusIdx(index)}
                  onClick={() => choose(option.label)}
                  className={cn(
                    "flex w-full items-center gap-2.5 rounded-lg px-2 py-1.5 text-left transition-colors",
                    focused ? "bg-foreground/[0.06]" : "hover:bg-foreground/[0.03]",
                  )}
                >
                  <span
                    className={cn(
                      "inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-md font-mono text-[11px] tabular-nums",
                      ticked
                        ? "bg-foreground text-background"
                        : focused
                          ? "bg-foreground/10 text-foreground"
                          : "bg-foreground/5 text-muted-foreground",
                    )}
                  >
                    {ticked ? <Check className="h-3 w-3" /> : index + 1}
                  </span>
                  {/* The name, then what it means on the same line, cut at the
                      edge - the whole sentence is the row's title. */}
                  <span className="min-w-0 flex-1 truncate" title={option.description ?? undefined}>
                    <span className="text-foreground text-sm">{option.label}</span>
                    {option.description && (
                      <span className="text-muted-foreground ml-2 text-xs">
                        {option.description}
                      </span>
                    )}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}

      {/* One row closes the slide: an answer of one's own, then whatever the
          prompt adds (Skip), then Continue where several may be picked. */}
      <div className="border-foreground/8 flex min-h-10 items-center gap-2 border-t px-3.5 py-1.5">
        {allowCustom && customOpen ? (
          <>
            <Pencil className="text-muted-foreground h-3.5 w-3.5 shrink-0" />
            <input
              ref={inputRef}
              type="text"
              value={customText}
              disabled={disabled}
              placeholder={t("typeYourAnswer")}
              onChange={(event) => setCustomText(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  submitCustom();
                }
              }}
              className="text-foreground placeholder:text-muted-foreground min-w-0 flex-1 bg-transparent text-base outline-none sm:text-sm"
            />
            <button
              type="button"
              disabled={disabled || !customText.trim()}
              onClick={submitCustom}
              className="text-foreground text-sm font-medium disabled:opacity-40"
            >
              {t("useThisAnswer")}
            </button>
            {trailing}
          </>
        ) : (
          <>
            {allowCustom ? (
              <button
                type="button"
                disabled={disabled}
                onClick={() => setCustomOpen(true)}
                className="text-muted-foreground hover:text-foreground flex items-center gap-2 text-sm transition-colors"
              >
                <Pencil className="h-3.5 w-3.5" />
                {t("somethingElse")}
              </button>
            ) : null}
            <span className="ml-auto flex items-center gap-3">
              {trailing}
              {multi && (
                <button
                  type="button"
                  disabled={disabled || picked.length === 0}
                  onClick={() => onAnswer({ answer: "", selected: picked, skipped: false })}
                  className="bg-foreground text-background rounded-lg px-3 py-1 text-sm font-medium disabled:opacity-40"
                >
                  {t("continue")}
                </button>
              )}
            </span>
          </>
        )}
      </div>
    </div>
  );
}
