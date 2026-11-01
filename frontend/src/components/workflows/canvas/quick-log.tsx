"use client";

import { Plus, ScrollText } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useState } from "react";

import {
  Button,
  Checkbox,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Textarea,
} from "@/components/ui";
import { cn } from "@/lib/utils";
import {
  canQuickLog,
  QUICK_LOG_DEFAULT_MESSAGE,
  QUICK_LOG_MESSAGE_MAX,
  type NodeInstance,
  type Port,
} from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

interface QuickLogProps {
  instance: NodeInstance;
  /** The step's output ports as the card draws them, `error` included when it routes errors. */
  outputs: Port[];
  /** The step's name, for the labels. */
  name: string;
  readOnly: boolean;
}

/**
 * The quick log's place on a card: "+ Log" on hover while the step has none, outside
 * the card's top right, and once it has one a LOG strip docked to the card's right
 * side, outside it and the card's full height, like an extension of the card. The
 * card moves its output handles to the strip's outer edge and marks each logged
 * output's row in it. Either opens the same popover. The card renders this before
 * its resize controls, so they stay on top.
 */
export function QuickLogControl({ instance, outputs, name, readOnly }: QuickLogProps) {
  const t = useTranslations("workflows");
  const [open, setOpen] = useState(false);
  const quickLog = instance.quick_log ?? null;
  if (quickLog === null && (readOnly || !canQuickLog(instance.definition_id))) return null;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        {quickLog === null ? (
          <button
            type="button"
            aria-label={t("quickLogAdd", { name })}
            title={t("quickLogAdd", { name })}
            // A button on the card, not a click on the node: xyflow would select it.
            onClick={(event) => event.stopPropagation()}
            className={cn(
              "nodrag nopan bg-background text-muted-foreground hover:text-foreground hover:border-foreground/40 focus-visible:ring-ring absolute top-1 left-full flex h-5 items-center justify-center gap-px rounded-full border px-1 shadow-sm transition-opacity outline-none focus-visible:ring-2",
              open ? "opacity-100" : "opacity-0 group-hover:opacity-100 focus-visible:opacity-100",
            )}
          >
            <Plus aria-hidden="true" className="size-2.5" />
            <ScrollText aria-hidden="true" className="size-3" />
          </button>
        ) : (
          <button
            type="button"
            aria-label={t("quickLogTab", { name })}
            onClick={(event) => event.stopPropagation()}
            // Over the card's border at top and bottom, so its edge runs on into the strip.
            // Only the word is turned: vertical writing on the strip itself would make its
            // logical insets horizontal and fold the strip into the card's corner.
            className="nodrag nopan bg-card text-primary focus-visible:ring-ring group/log absolute -top-px -bottom-px left-full flex w-5 items-start justify-center overflow-hidden rounded-r-xl border border-l-0 pt-2 text-[10px] leading-none font-semibold tracking-wider uppercase outline-none focus-visible:ring-2 focus-visible:ring-inset"
          >
            <span
              aria-hidden="true"
              className="bg-primary/10 group-hover/log:bg-primary/20 absolute inset-0"
            />
            <span className="relative [writing-mode:vertical-rl]">{t("quickLogTabText")}</span>
          </button>
        )}
      </PopoverTrigger>
      <PopoverContent
        className="w-80"
        align="start"
        side="right"
        onClick={(event) => event.stopPropagation()}
        // Typing and Tab belong to the form: the canvas shortcuts (the picker, undo, copy) stay out.
        onKeyDown={(event) => event.stopPropagation()}
        onCloseAutoFocus={(event) => event.preventDefault()}
      >
        <QuickLogForm
          instance={instance}
          outputs={outputs}
          readOnly={readOnly}
          onDone={() => setOpen(false)}
        />
      </PopoverContent>
    </Popover>
  );
}

function QuickLogForm({
  instance,
  outputs,
  readOnly,
  onDone,
}: Omit<QuickLogProps, "name"> & { onDone: () => void }) {
  const t = useTranslations("workflows");
  const updateNodeDetails = useWorkflowEditorStore((state) => state.updateNodeDetails);
  const quickLog = instance.quick_log ?? null;
  const id = useId();
  const [message, setMessage] = useState(quickLog?.message ?? QUICK_LOG_DEFAULT_MESSAGE);
  const [ticked, setTicked] = useState(
    () => new Set(quickLog?.outputs ?? outputs.map((port) => port.id)),
  );
  const chosen = outputs.filter((port) => ticked.has(port.id)).map((port) => port.id);
  // A step with no outputs (a raise, a final output) logs only when it fails.
  const valid = message.trim() !== "" && (outputs.length === 0 || chosen.length > 0);

  const save = () => {
    // Every box ticked is "every output", which also follows an output added later.
    const all = chosen.length === outputs.length;
    updateNodeDetails(instance.id, {
      quick_log: { message, outputs: all ? null : chosen },
    });
    onDone();
  };

  return (
    <div className="space-y-3">
      <p className="text-sm font-medium">{t("quickLogTitle")}</p>
      <div className="space-y-1">
        <label htmlFor={`${id}-message`} className="text-muted-foreground text-xs">
          {t("quickLogMessage")}
        </label>
        <Textarea
          id={`${id}-message`}
          value={message}
          rows={2}
          maxLength={QUICK_LOG_MESSAGE_MAX}
          disabled={readOnly}
          onChange={(event) => setMessage(event.target.value)}
          className="font-mono text-xs"
        />
      </div>
      {outputs.length === 0 ? (
        <p className="text-muted-foreground text-xs">{t("quickLogNoPorts")}</p>
      ) : (
        <fieldset className="space-y-1.5">
          <legend className="text-muted-foreground mb-1 text-xs">{t("quickLogOutputs")}</legend>
          {outputs.map((port) => (
            <label key={port.id} className="flex items-center gap-2 text-sm">
              <Checkbox
                checked={ticked.has(port.id)}
                disabled={readOnly}
                onCheckedChange={(on) =>
                  setTicked((previous) => {
                    const next = new Set(previous);
                    if (on === true) next.add(port.id);
                    else next.delete(port.id);
                    return next;
                  })
                }
              />
              {port.label}
            </label>
          ))}
          {chosen.length === 0 && !readOnly && (
            <p role="alert" className="text-destructive text-xs">
              {t("quickLogNoOutputs")}
            </p>
          )}
        </fieldset>
      )}
      {!readOnly && (
        <div className="flex justify-end gap-2">
          {quickLog !== null && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => {
                updateNodeDetails(instance.id, { quick_log: null });
                onDone();
              }}
            >
              {t("quickLogRemove")}
            </Button>
          )}
          <Button type="button" size="sm" disabled={!valid} onClick={save}>
            {t("quickLogSave")}
          </Button>
        </div>
      )}
    </div>
  );
}
