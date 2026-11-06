"use client";

import { useState } from "react";
import { ChevronRight, Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button, Card, CardContent, CardTitle, Input, Textarea, Label } from "@/components/ui";

import type { StarterIcons, StarterTitles } from "@/types/agents";
import { StarterIconPicker } from "./starter-icon-picker";

/** The spec's own ceilings - `MAX_STARTERS` and `Starter` in `app/agents/spec.py`. */
const MAX_STARTERS = 4;
const MAX_STARTER_LENGTH = 200;

interface StartersPanelProps {
  starters: string[];
  icons?: StarterIcons;
  titles?: StarterTitles;
  disabled: boolean;
  onChange: (starters: string[], icons: StarterIcons, titles: StarterTitles) => void;
}

/**
 * The first messages an empty chat offers whoever opens this agent (#2301).
 *
 * A person who has never used the agent learns what it is for from these more
 * than from its description, so they sit beside the instructions. Published
 * with the rest of the spec; none, and the chat shows its own.
 */
export function StartersPanel({
  starters,
  icons = {},
  titles = {},
  disabled,
  onChange,
}: StartersPanelProps) {
  const t = useTranslations("agents");
  const [expanded, setExpanded] = useState(false);
  const [adding, setAdding] = useState("");
  const draft = adding.trim();
  const full = starters.length >= MAX_STARTERS;

  const add = (): void => {
    onChange(
      [...starters, draft],
      metadataFor([...starters, draft], icons),
      metadataFor([...starters, draft], titles),
    );
    setAdding("");
  };

  const edit = (index: number, text: string): void => {
    const previous = starters[index] ?? "";
    const next = starters.map((one, at) => (at === index ? text : one));
    const updated = { ...icons };
    const icon = icons[previous.trim()];
    if (icon && text.trim()) updated[text.trim()] = icon;
    const updatedTitles = { ...titles };
    const title = titles[previous.trim()];
    if (title && text.trim()) updatedTitles[text.trim()] = title;
    onChange(next, metadataFor(next, updated), metadataFor(next, updatedTitles));
  };

  return (
    <Card className="@container">
      <details
        className="group"
        open={expanded}
        onToggle={(event) => setExpanded(event.currentTarget.open)}
      >
        <summary
          data-tour="agent-starters"
          className="flex cursor-pointer list-none items-center gap-3 rounded-xl p-4 focus-visible:outline-2 focus-visible:outline-offset-2 sm:p-5 [&::-webkit-details-marker]:hidden"
        >
          <ChevronRight
            className="text-muted-foreground size-4 shrink-0 transition-transform group-open:rotate-90"
            aria-hidden
          />
          <div className="min-w-0 flex-1 space-y-1">
            <CardTitle>{t("startersTitle")}</CardTitle>
            <p className="text-muted-foreground text-[13px] leading-5">
              {t("startersHint", { max: MAX_STARTERS })}
            </p>
          </div>
          <span className="text-muted-foreground bg-foreground/[0.05] rounded-md px-2 py-1 text-xs tabular-nums">
            {starters.length}/{MAX_STARTERS}
          </span>
        </summary>
        <CardContent className="space-y-3">
          {starters.length > 0 && (
            <ul className="grid gap-3 @2xl:grid-cols-2">
              {starters.map((starter, index) => (
                <li key={index} className="bg-background/30 space-y-3 rounded-lg border p-3">
                  <div className="flex items-center gap-2">
                    <StarterIconPicker
                      number={index + 1}
                      value={icons[starter.trim()] ?? "message"}
                      disabled={disabled || !starter.trim()}
                      onChange={(icon) =>
                        onChange(
                          starters,
                          metadataFor(starters, { ...icons, [starter.trim()]: icon }),
                          metadataFor(starters, titles),
                        )
                      }
                    />
                    <Input
                      aria-label={t("starterTitle", { number: index + 1 })}
                      value={titles[starter.trim()] ?? ""}
                      maxLength={80}
                      disabled={disabled || !starter.trim()}
                      placeholder={t("starterTitlePlaceholder")}
                      onChange={(event) =>
                        onChange(
                          starters,
                          icons,
                          metadataFor(starters, {
                            ...titles,
                            [starter.trim()]: event.target.value,
                          }),
                        )
                      }
                      className="h-8 text-base sm:text-sm"
                    />
                    <Button
                      type="button"
                      size="icon"
                      variant="ghost"
                      aria-label={t("removeStarter", { number: index + 1 })}
                      disabled={disabled}
                      onClick={() => {
                        const next = starters.filter((_, at) => at !== index);
                        onChange(next, metadataFor(next, icons), metadataFor(next, titles));
                      }}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                  <div className="space-y-1.5">
                    <Label
                      htmlFor={`starter-message-${index}`}
                      className="text-muted-foreground text-xs"
                    >
                      {t("starterMessageLabel")}
                    </Label>
                    <Textarea
                      id={`starter-message-${index}`}
                      aria-label={t("starterNumber", { number: index + 1 })}
                      value={starter}
                      maxLength={MAX_STARTER_LENGTH}
                      disabled={disabled}
                      onChange={(event) => edit(index, event.target.value)}
                      className="min-h-16 text-base sm:text-sm"
                    />
                  </div>
                </li>
              ))}
            </ul>
          )}
          {!full && (
            <div className="flex items-center gap-2">
              <Input
                aria-label={t("newStarter")}
                value={adding}
                maxLength={MAX_STARTER_LENGTH}
                disabled={disabled}
                placeholder={t("newStarterPlaceholder")}
                onChange={(event) => setAdding(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && draft) {
                    event.preventDefault();
                    add();
                  }
                }}
                className="h-8 text-base sm:text-sm"
              />
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={disabled || !draft}
                onClick={add}
              >
                <Plus className="h-4 w-4" />
                {t("addStarter")}
              </Button>
            </div>
          )}
        </CardContent>
      </details>
    </Card>
  );
}

/** Text keys keep the icon attached when rows are removed or reordered. */
function metadataFor<T>(starters: string[], values: Record<string, T>): Record<string, T> {
  const kept = new Set(starters.map((text) => text.trim()));
  return Object.fromEntries(Object.entries(values).filter(([text]) => kept.has(text)));
}
