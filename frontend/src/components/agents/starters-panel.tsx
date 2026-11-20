"use client";

import { useId, useRef, useState } from "react";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { BuildSection } from "./build-section";
import { useDefaultChatSuggestions } from "@/components/chat/chat-empty-state";
import {
  Button,
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
  Switch,
  Textarea,
} from "@/components/ui";
import { STARTER_ICONS } from "@/lib/starter-icons";
import type { StarterIcon, StarterIcons, StarterTitles } from "@/types/agents";
import { StarterIconPicker } from "./starter-icon-picker";

/** The spec's own ceilings - `MAX_STARTERS` and `Starter` in `app/agents/spec.py`. */
const MAX_STARTERS = 4;
const MAX_STARTER_LENGTH = 200;

const DEFAULT_ICONS: Record<string, StarterIcon> = {
  capabilities: "compass",
  docs: "file",
  routine: "calendar",
  email: "mail",
  visualExplain: "sparkles",
  visualCompare: "chart",
  visualTool: "code",
  visualMap: "compass",
};

interface StarterDraft {
  index: number | null;
  message: string;
  title: string;
  icon: StarterIcon;
}

interface StartersPanelProps {
  starters: string[];
  draws?: boolean;
  icons?: StarterIcons;
  titles?: StarterTitles;
  disabled: boolean;
  showStarters?: boolean;
  onShowStartersChange?: (show: boolean) => void;
  onChange: (starters: string[], icons: StarterIcons, titles: StarterTitles) => void;
}

export function StartersPanel({
  starters,
  draws = false,
  icons = {},
  titles = {},
  disabled,
  showStarters = true,
  onShowStartersChange,
  onChange,
}: StartersPanelProps) {
  const t = useTranslations("agents");
  const common = useTranslations("common");
  const defaults = useDefaultChatSuggestions(draws);
  const [editor, setEditor] = useState<StarterDraft | null>(null);
  const cardId = useId();
  const opener = useRef<HTMLButtonElement>(null);
  const usingDefaults = starters.length === 0;
  const cards = usingDefaults
    ? defaults.map((entry) => ({
        icon: DEFAULT_ICONS[entry.key] ?? "message",
        Icon: entry.icon,
        title: entry.title,
        message: entry.prompt,
      }))
    : starters.map((message) => {
        const icon = icons[message.trim()] ?? "message";
        return { icon, Icon: STARTER_ICONS[icon], title: titles[message.trim()] ?? "", message };
      });

  const update = (remove = false) => {
    if (!editor || disabled || (editor.index === null && starters.length >= MAX_STARTERS)) return;
    const message = editor.message.trim();
    if (!remove && !message) return;
    const index = editor.index;
    const next = (index === null && usingDefaults ? [] : cards).map((card) => ({
      message: card.message,
      title: card.title,
      icon: card.icon,
    }));

    if (index === null) next.push({ ...editor, message });
    else if (remove) next.splice(index, 1);
    else next[index] = { ...editor, message };

    onChange(
      next.map((card) => card.message),
      Object.fromEntries(
        next
          .filter((card) => card.icon !== "message")
          .map((card) => [card.message.trim(), card.icon]),
      ),
      Object.fromEntries(
        next
          .filter((card) => card.title.trim())
          .map((card) => [card.message.trim(), card.title.trim()]),
      ),
    );
    setEditor(null);
  };

  return (
    <BuildSection
      className="@container"
      data-tour="agent-starters"
      defaultOpen
      title={t("startersTitle")}
      description={t("startersHint", { max: MAX_STARTERS })}
      headerEnd={
        !usingDefaults && (
          <span className="text-muted-foreground bg-muted rounded-md px-2 py-1 text-xs tabular-nums">
            {starters.length}/{MAX_STARTERS}
          </span>
        )
      }
    >
      {onShowStartersChange && (
        <label className="flex min-h-9 items-center justify-between gap-3 text-sm">
          {t("showStarters")}
          <Switch
            checked={showStarters}
            onCheckedChange={onShowStartersChange}
            disabled={disabled}
          />
        </label>
      )}
      {showStarters && (
        <ul className="grid auto-rows-fr gap-3 @xl:grid-cols-2">
          {cards.map(({ icon, Icon, title, message }, index) => (
            <li key={index} className="min-w-0">
              <button
                type="button"
                disabled={disabled}
                aria-label={disabled ? undefined : common("editNamed", { name: title || message })}
                aria-describedby={title && title !== message ? `${cardId}-${index}` : undefined}
                onClick={(event) => {
                  opener.current = event.currentTarget;
                  setEditor({ index, message, title, icon });
                }}
                className="group border-border bg-background/45 enabled:hover:bg-muted/55 enabled:hover:border-foreground/20 focus-visible:outline-ring flex h-full w-full min-w-0 items-start gap-3 rounded-xl border p-3 text-left transition-colors focus-visible:outline-2 focus-visible:outline-offset-[-2px] motion-reduce:transition-none"
              >
                <span className="text-muted-foreground bg-muted/60 grid size-8 shrink-0 place-items-center rounded-lg">
                  <Icon className="size-4" aria-hidden />
                </span>
                <span className="min-w-0 flex-1 space-y-0.5">
                  <span className="block text-sm font-medium [overflow-wrap:anywhere]">
                    {title || message}
                  </span>
                  {title && title !== message && (
                    <span
                      id={`${cardId}-${index}`}
                      className="text-muted-foreground block text-[13px] leading-relaxed [overflow-wrap:anywhere]"
                    >
                      {message}
                    </span>
                  )}
                </span>
                {!disabled && (
                  <Pencil className="text-muted-foreground mt-1 size-3.5 shrink-0" aria-hidden />
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
      {showStarters && !disabled && starters.length < MAX_STARTERS && (
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={(event) => {
            opener.current = event.currentTarget;
            setEditor({ index: null, message: "", title: "", icon: "message" });
          }}
        >
          <Plus className="size-4" aria-hidden />
          {t("addStarter")}
        </Button>
      )}
      <Dialog open={editor !== null} onOpenChange={(open) => !open && setEditor(null)}>
        {editor && (
          <DialogContent
            aria-describedby={undefined}
            onCloseAutoFocus={(event) => {
              event.preventDefault();
              opener.current?.focus({ preventScroll: true });
            }}
          >
            <DialogHeader>
              <DialogTitle>
                {editor.index === null
                  ? t("newStarter")
                  : t("starterNumber", { number: editor.index + 1 })}
              </DialogTitle>
            </DialogHeader>
            <form
              className="space-y-4"
              onSubmit={(event) => {
                event.preventDefault();
                update();
              }}
            >
              <div className="space-y-2">
                <Label htmlFor="starter-title">{t("starterTitlePlaceholder")}</Label>
                <div className="flex items-center gap-2">
                  <StarterIconPicker
                    number={editor.index === null ? starters.length + 1 : editor.index + 1}
                    value={editor.icon}
                    disabled={disabled}
                    onChange={(icon) => setEditor({ ...editor, icon })}
                  />
                  <Input
                    id="starter-title"
                    value={editor.title}
                    maxLength={80}
                    disabled={disabled}
                    onChange={(event) => setEditor({ ...editor, title: event.target.value })}
                  />
                </div>
              </div>
              <div className="space-y-2">
                <Label htmlFor="starter-message">{t("starterMessageLabel")}</Label>
                <Textarea
                  id="starter-message"
                  data-initial-focus
                  value={editor.message}
                  maxLength={MAX_STARTER_LENGTH}
                  rows={4}
                  disabled={disabled}
                  onChange={(event) => setEditor({ ...editor, message: event.target.value })}
                />
              </div>
              <DialogFooter>
                {editor.index !== null && (
                  <Button
                    type="button"
                    variant="ghost"
                    className="mr-auto"
                    disabled={disabled}
                    onClick={() => update(true)}
                  >
                    <Trash2 className="size-4" aria-hidden />
                    {t("removeStarter", { number: editor.index + 1 })}
                  </Button>
                )}
                <Button type="button" variant="outline" onClick={() => setEditor(null)}>
                  {common("cancel")}
                </Button>
                <Button type="submit" disabled={disabled || !editor.message.trim()}>
                  {common("save")}
                </Button>
              </DialogFooter>
            </form>
          </DialogContent>
        )}
      </Dialog>
    </BuildSection>
  );
}
