"use client";

import { useState } from "react";
import { Pin, Send, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button, Input } from "@/components/ui";

/**
 * The test panel's prompts: the pinned ones, rerun with a click, and a box that
 * asks every chat in the panel at once or pins what it holds (#2074).
 *
 * Asking from here is what makes a comparison fair - both versions get the same
 * words at the same moment, not whatever was typed into each separately.
 */
export function TestPanelPrompts({
  pinned,
  comparing,
  onAsk,
  onPinnedChange,
}: {
  pinned: string[];
  comparing: boolean;
  onAsk: (text: string) => void;
  onPinnedChange: (pinned: string[]) => void;
}) {
  const t = useTranslations("agents");
  const [text, setText] = useState("");
  const trimmed = text.trim();

  const pin = () => {
    if (!pinned.includes(trimmed)) onPinnedChange([...pinned, trimmed]);
    setText("");
  };

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {pinned.map((entry) => (
        <span
          key={entry}
          className="bg-muted flex max-w-full items-center gap-1 rounded-full py-0.5 pr-1 pl-2.5 text-xs"
        >
          <button
            type="button"
            className="truncate hover:underline"
            title={entry}
            onClick={() => onAsk(entry)}
          >
            {entry}
          </button>
          <button
            type="button"
            aria-label={t("testPanelUnpin", { text: entry })}
            onClick={() => onPinnedChange(pinned.filter((kept) => kept !== entry))}
            className="text-muted-foreground hover:text-foreground rounded-full p-0.5"
          >
            <X className="h-3 w-3" />
          </button>
        </span>
      ))}
      <form
        className="flex min-w-40 flex-1 items-center gap-1"
        onSubmit={(event) => {
          event.preventDefault();
          onAsk(trimmed);
          setText("");
        }}
      >
        <Input
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder={comparing ? t("testPanelAskBothPlaceholder") : t("testPanelPinPlaceholder")}
          aria-label={t("testPanelPrompt")}
          className="h-7 text-xs"
          maxLength={500}
        />
        <Button
          type="submit"
          variant="ghost"
          size="icon"
          className="h-7 w-7"
          aria-label={comparing ? t("testPanelAskBoth") : t("testPanelAsk")}
          disabled={!trimmed}
        >
          <Send className="h-3.5 w-3.5" />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="h-7 w-7"
          aria-label={t("testPanelPin")}
          disabled={!trimmed}
          onClick={pin}
        >
          <Pin className="h-3.5 w-3.5" />
        </Button>
      </form>
    </div>
  );
}
