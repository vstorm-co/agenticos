"use client";

import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input,
} from "@/components/ui";

/** The spec's own ceilings - `MAX_STARTERS` and `Starter` in `app/agents/spec.py`. */
const MAX_STARTERS = 4;
const MAX_STARTER_LENGTH = 200;

interface StartersPanelProps {
  starters: string[];
  disabled: boolean;
  onChange: (starters: string[]) => void;
}

/**
 * The first messages an empty chat offers whoever opens this agent (#2301).
 *
 * A person who has never used the agent learns what it is for from these more
 * than from its description, so they sit beside the instructions. Published
 * with the rest of the spec; none, and the chat shows its own.
 */
export function StartersPanel({ starters, disabled, onChange }: StartersPanelProps) {
  const t = useTranslations("agents");
  const [adding, setAdding] = useState("");
  const draft = adding.trim();
  const full = starters.length >= MAX_STARTERS;

  const add = () => {
    onChange([...starters, draft]);
    setAdding("");
  };

  return (
    <Card>
      {/* The header, not the card: a bounded anchor for the walkthrough's stop. */}
      <CardHeader data-tour="agent-starters">
        <CardTitle>{t("startersTitle")}</CardTitle>
        <CardDescription>{t("startersHint", { max: MAX_STARTERS })}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {starters.length > 0 && (
          <ul className="space-y-2">
            {starters.map((starter, index) => (
              <li key={index} className="flex items-center gap-2">
                <Input
                  aria-label={t("starterNumber", { number: index + 1 })}
                  value={starter}
                  maxLength={MAX_STARTER_LENGTH}
                  disabled={disabled}
                  onChange={(event) =>
                    onChange(starters.map((one, at) => (at === index ? event.target.value : one)))
                  }
                  className="h-8 text-base sm:text-sm"
                />
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  aria-label={t("removeStarter", { number: index + 1 })}
                  disabled={disabled}
                  onClick={() => onChange(starters.filter((_, at) => at !== index))}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
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
    </Card>
  );
}
