"use client";

import { useState, type Dispatch, type SetStateAction } from "react";
import { useTranslations } from "next-intl";

import {
  Button,
  Checkbox,
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  SearchInput,
} from "@/components/ui";
import type { ToolPickerState } from "@/components/mcp/mcp-server-list-types";
import { DIALOG_COLUMN, DIALOG_FORM } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";

interface McpToolPickerDialogProps {
  toolPicker: ToolPickerState | null;
  setToolPicker: Dispatch<SetStateAction<ToolPickerState | null>>;
  submitting: boolean;
  onSave: () => void;
}

/**
 * Which of a server's tools it exposes.
 *
 * A connected server offers twenty-five of them and Notion offers more, so the
 * list is the whole dialog: it is bounded and scrolls inside itself rather than
 * growing the dialog past the screen, it is searchable, and it says how many of
 * how many are on. Without those three it was a wall of switches somebody had to
 * scroll to count - and the count is the only thing a person is actually
 * deciding here.
 *
 * Checkboxes rather than switches. A switch is a setting that takes effect; these
 * are a selection that is saved by the button below, and twenty-five switches
 * read as twenty-five separate decisions already made.
 */
export function McpToolPickerDialog({
  toolPicker,
  setToolPicker,
  submitting,
  onSave,
}: McpToolPickerDialogProps) {
  const t = useTranslations("mcp");
  const [query, setQuery] = useState("");

  const tools = toolPicker?.tools ?? [];
  const needle = query.trim().toLowerCase();
  // Descriptions too: somebody looking for "upload" does not know the tool is
  // called `create-file-upload`. Filtered per render rather than memoised: the
  // list is rebuilt by the caller on every render anyway, so a memo over it
  // recomputes each time and only reads as a saving.
  const shown = needle
    ? tools.filter(
        (tool) =>
          tool.name.toLowerCase().includes(needle) ||
          tool.description.toLowerCase().includes(needle),
      )
    : tools;

  const setChecked = (next: (previous: Set<string>) => Set<string>) =>
    setToolPicker((previous) =>
      previous === null ? previous : { ...previous, checked: next(previous.checked) },
    );

  // All and none act on what the search narrowed to, not on the catalogue: the
  // reason to search first is to act on the result.
  const allShownOn = shown.length > 0 && shown.every((tool) => toolPicker?.checked.has(tool.name));

  return (
    <Dialog
      open={toolPicker !== null}
      onOpenChange={(open) => !open && !submitting && setToolPicker(null)}
    >
      <DialogContent className={cn(DIALOG_FORM, DIALOG_COLUMN)}>
        <DialogHeader>
          <DialogTitle>{t("toolsFrom", { name: toolPicker?.connection.name ?? "" })}</DialogTitle>
        </DialogHeader>
        <p className="text-foreground/55 shrink-0 text-xs">
          {toolPicker?.appliesTo === "agent"
            ? t("whichToolsAgent")
            : t("whichToolsConnection", { scope: toolPicker?.scope ?? "personal" })}
        </p>

        {tools.length > 0 && (
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            <SearchInput value={query} onChange={setQuery} placeholder={t("searchTools")} />
            <span className="text-muted-foreground text-xs" role="status">
              {t("toolsSelected", { on: toolPicker?.checked.size ?? 0, total: tools.length })}
            </span>
            <Button
              variant="ghost"
              size="sm"
              className="ml-auto"
              onClick={() =>
                setChecked((previous) => {
                  const next = new Set(previous);
                  for (const tool of shown) {
                    if (allShownOn) next.delete(tool.name);
                    else next.add(tool.name);
                  }
                  return next;
                })
              }
            >
              {allShownOn ? t("selectNone") : t("selectAll")}
            </Button>
          </div>
        )}

        <ul className="border-foreground/10 divide-foreground/8 min-h-0 flex-1 divide-y overflow-y-auto rounded-xl border">
          {shown.map((tool) => (
            <li key={tool.name}>
              {/* The whole row is the control: twenty-five small targets at the
                  right edge is a lot of travel to switch six things off. */}
              <label className="hover:bg-foreground/4 flex cursor-pointer items-start gap-3 px-4 py-2.5">
                <Checkbox
                  checked={toolPicker?.checked.has(tool.name) ?? false}
                  onCheckedChange={(on) =>
                    setChecked((previous) => {
                      const next = new Set(previous);
                      if (on === true) next.add(tool.name);
                      else next.delete(tool.name);
                      return next;
                    })
                  }
                  className="mt-0.5"
                  aria-label={tool.name}
                />
                <span className="min-w-0 flex-1">
                  <span className="text-foreground block font-mono text-xs">{tool.name}</span>
                  {tool.description && (
                    <span className="text-foreground/55 mt-0.5 block truncate text-xs">
                      {tool.description}
                    </span>
                  )}
                </span>
              </label>
            </li>
          ))}
          {shown.length === 0 && (
            <li className="text-muted-foreground px-4 py-6 text-center text-xs">
              {/* Two different nothings. A server nobody has probed has no list
                  to choose from and the reader has somewhere to go about it;
                  a search that matched none of twenty-five is their own doing.
                  One message for both said "No tool matches that" under an
                  empty search box, which is the wrong answer and hides the
                  reason. */}
              {tools.length === 0 ? (
                <>
                  {t("noToolsProbed")}
                  <span className="mt-1 block">{t("checkItOnTheServersPage")}</span>
                </>
              ) : (
                t("noToolMatches")
              )}
            </li>
          )}
        </ul>

        <DialogFooter className="shrink-0">
          <Button variant="ghost" onClick={() => setToolPicker(null)} disabled={submitting}>
            {t("cancel2")}
          </Button>
          <Button onClick={onSave} disabled={submitting || toolPicker?.checked.size === 0}>
            {submitting ? t("saving2") : t("saveSelection")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
