"use client";

import type { Dispatch, SetStateAction } from "react";
import { useTranslations } from "next-intl";

import {
  Button,
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Switch,
} from "@/components/ui";
import type { ToolPickerState } from "@/components/mcp/mcp-server-list-types";

interface McpToolPickerDialogProps {
  toolPicker: ToolPickerState | null;
  setToolPicker: Dispatch<SetStateAction<ToolPickerState | null>>;
  submitting: boolean;
  onSave: () => void;
}

export function McpToolPickerDialog({
  toolPicker,
  setToolPicker,
  submitting,
  onSave,
}: McpToolPickerDialogProps) {
  const t = useTranslations("mcp");

  return (
    <Dialog
      open={toolPicker !== null}
      onOpenChange={(open) => !open && !submitting && setToolPicker(null)}
    >
      <DialogContent className="max-h-[80vh] scrollbar-thin overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t("toolsFrom", { name: toolPicker?.connection.name ?? "" })}</DialogTitle>
        </DialogHeader>
        <p className="text-foreground/55 text-xs">
          {t("whichToolsExposed", { scope: toolPicker?.scope ?? "personal" })}
        </p>
        <ul className="border-foreground/10 divide-foreground/8 divide-y rounded-xl border">
          {toolPicker?.tools.map((tool) => (
            <li key={tool.name} className="flex items-start gap-3 px-4 py-2.5">
              <div className="min-w-0 flex-1">
                <code className="text-foreground bg-foreground/8 rounded px-1.5 py-0.5 font-mono text-xs">
                  {tool.name}
                </code>
                {tool.description && (
                  <p className="text-foreground/55 mt-1 line-clamp-2 text-xs">{tool.description}</p>
                )}
              </div>
              <Switch
                checked={toolPicker.checked.has(tool.name)}
                onCheckedChange={(on) =>
                  setToolPicker((previous) => {
                    if (!previous) return previous;
                    const next = new Set(previous.checked);
                    if (on) next.add(tool.name);
                    else next.delete(tool.name);
                    return { ...previous, checked: next };
                  })
                }
                aria-label={t("toggleNamed", { name: tool.name })}
              />
            </li>
          ))}
        </ul>
        <DialogFooter>
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
