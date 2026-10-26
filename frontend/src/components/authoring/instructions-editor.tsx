"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { Textarea } from "@/components/ui";
import { useWideScreen } from "@/hooks/use-wide-screen";
import { cn } from "@/lib/utils";
import { DiffView } from "./diff-view";

/**
 * The passage a person's edit of the whole instructions comes to, as the
 * suggestion's own contract takes it: the text between the parts before and after
 * the suggested passage, which must stay as they are. `null` when the edit reaches
 * outside the passage, which is a change to the draft rather than to the suggestion.
 */
export function editedPassage(edited: string, before: string, after: string): string | null {
  if (edited.length < before.length + after.length) return null;
  if (!edited.startsWith(before) || !edited.endsWith(after)) return null;
  return edited.slice(before.length, edited.length - after.length);
}

/**
 * The whole instructions with a suggestion in them: the current version to read
 * and the proposed one to edit, side by side on a wide screen and as two tabs on
 * a phone, with the change between them redrawn as the person types.
 */
export function InstructionsEditor({
  current,
  value,
  outside,
  onChange,
}: {
  current: string;
  value: string;
  /** Whether the edit reaches outside the suggested passage. */
  outside: boolean;
  onChange: (value: string) => void;
}) {
  const t = useTranslations("authoring.instructionsEditor");
  const wide = useWideScreen();
  const [tab, setTab] = useState<"current" | "proposed">("proposed");
  const currentPane = (
    <div className="min-w-0 space-y-1">
      <h4 className="text-muted-foreground text-xs font-medium">{t("current")}</h4>
      <pre
        aria-label={t("current")}
        className="bg-muted/40 max-h-96 overflow-auto rounded-md p-3 font-mono text-xs break-words whitespace-pre-wrap"
      >
        {current}
      </pre>
    </div>
  );
  const proposedPane = (
    <div className="min-w-0 space-y-1">
      <h4 className="text-muted-foreground text-xs font-medium">{t("proposed")}</h4>
      <Textarea
        aria-label={t("proposed")}
        className="max-h-96 min-h-48 font-mono text-xs"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </div>
  );
  return (
    <div className="space-y-3">
      {wide ? (
        <div className="grid grid-cols-2 gap-3">
          {currentPane}
          {proposedPane}
        </div>
      ) : (
        <div className="space-y-2">
          <div role="tablist" aria-label={t("panes")} className="flex gap-1">
            {(["current", "proposed"] as const).map((pane) => (
              <button
                key={pane}
                type="button"
                role="tab"
                aria-selected={tab === pane}
                className={cn(
                  "rounded px-2 py-1 text-xs",
                  tab === pane ? "bg-muted font-medium" : "text-muted-foreground",
                )}
                onClick={() => setTab(pane)}
              >
                {t(pane === "current" ? "current" : "proposedTab")}
              </button>
            ))}
          </div>
          {tab === "current" ? currentPane : proposedPane}
        </div>
      )}
      {outside && (
        <p role="alert" className="text-warning text-sm">
          {t("outside")}
        </p>
      )}
      <DiffView before={current} after={value} />
    </div>
  );
}
