"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { CodeArea } from "@/components/ui/code-area";

interface StartRunDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Whether a published version exists to run for real. */
  canRunLive: boolean;
  /** Whether this caller may test the draft (`workflows:edit`). */
  canTest: boolean;
  busy?: boolean;
  onStart: (start: { mode: "real" | "test"; input: Record<string, unknown> }) => void;
}

/** Parse the input box: a JSON object, or the message saying what is wrong. */
export function parseRunInput(text: string): Record<string, unknown> | string {
  if (text.trim() === "") return {};
  try {
    const value: unknown = JSON.parse(text);
    if (typeof value !== "object" || value === null || Array.isArray(value)) return "notObject";
    return value as Record<string, unknown>;
  } catch {
    return "notJson";
  }
}

/**
 * Start a run by hand - of the draft, to try it, or of the published version.
 *
 * The input is what `core.input` hands the graph as `payload`: a JSON object,
 * typed here the way an API caller would send it.
 */
export function StartRunDialog({
  open,
  onOpenChange,
  canRunLive,
  canTest,
  busy,
  onStart,
}: StartRunDialogProps) {
  const t = useTranslations("pages.workflows");
  const [mode, setMode] = useState<"real" | "test">(canTest ? "test" : "real");
  const [text, setText] = useState("{\n  \n}");
  const parsed = parseRunInput(text);
  const invalid = typeof parsed === "string";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("startRunTitle")}</DialogTitle>
          <DialogDescription>{t("startRunDescription")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="run-mode">{t("startRunMode")}</Label>
            <Select value={mode} onValueChange={(value) => setMode(value as "real" | "test")}>
              <SelectTrigger id="run-mode">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {canTest && <SelectItem value="test">{t("modeTest")}</SelectItem>}
                {canRunLive && <SelectItem value="real">{t("modeReal")}</SelectItem>}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label>{t("startRunInput")}</Label>
            <CodeArea
              name="input.json"
              aria-label={t("startRunInput")}
              value={text}
              onChange={setText}
              className="min-h-40"
            />
            {invalid && (
              <p className="text-destructive text-xs">{t(`startRunInputInvalid.${parsed}`)}</p>
            )}
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button
            disabled={invalid || busy || (mode === "real" && !canRunLive)}
            onClick={() => {
              if (typeof parsed !== "string") onStart({ mode, input: parsed });
            }}
          >
            {t("startRun")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
