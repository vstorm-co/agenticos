"use client";

import { useId, useState, useEffect, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { RotateCcw } from "lucide-react";
import { Button, Checkbox, Label } from "@/components/ui";
import { useUnsavedChanges } from "@/hooks/use-unsaved-changes";
import { cn } from "@/lib/utils";
import { NAV_GROUPS, presentedNavigation } from "@/lib/nav-sections";

const GROUPS = NAV_GROUPS.filter((group) => !group.adminOnly && !group.switcherOnly);

/** Draft a complete selection before replacing this one presentation field. */
export function ConsoleNavigationControls({
  value,
  allowed,
  inherited,
  simple,
  disabled,
  onSave,
  preview,
  onDirtyChange,
  showUnavailable = true,
  scrollable = false,
}: {
  value: readonly string[] | null | undefined;
  allowed: readonly string[];
  inherited?: readonly string[];
  simple?: readonly string[];
  disabled: boolean;
  onSave: (value: string[] | null, onSaved: () => void) => void;
  preview?: (selection: readonly string[]) => ReactNode;
  onDirtyChange?: (dirty: boolean) => void;
  showUnavailable?: boolean;
  scrollable?: boolean;
}) {
  const id = useId();
  const t = useTranslations("consoleExperience.presentation");
  const common = useTranslations("common");
  const [draft, setDraft] = useState<string[] | null | undefined>(undefined);
  const selected = (draft === undefined ? value : draft) ?? inherited ?? allowed;
  const selection = allowed.filter((entry) => selected.includes(entry));
  const dirty = draft !== undefined;
  useEffect(() => {
    onDirtyChange?.(dirty);
  }, [dirty, onDirtyChange]);
  useUnsavedChanges(id, { dirty, discard: () => setDraft(undefined) });
  return (
    <div className={cn("space-y-4", scrollable && "flex min-h-0 flex-1 flex-col space-y-0")}>
      <div
        className={cn(
          "space-y-4",
          scrollable && "min-h-0 flex-1 overflow-y-auto overscroll-contain pr-1",
        )}
      >
        {simple && (
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={disabled}
              onClick={() => setDraft(allowed.filter((entry) => simple.includes(entry)))}
            >
              {t("simple")}
            </Button>
          </div>
        )}
        <p className="text-muted-foreground text-xs leading-5">{t("navigationHint")}</p>
        <div className={cn("grid gap-6", preview && "lg:grid-cols-2")}>
          <ConsoleNavigationSelection
            value={selection}
            allowed={allowed}
            disabled={disabled}
            onChange={setDraft}
            showUnavailable={showUnavailable}
          />
          {preview?.(selection)}
        </div>
      </div>
      <div
        className={cn(
          "flex flex-col gap-3 border-t pt-4 sm:flex-row sm:items-center sm:justify-between",
          scrollable && "mt-4 shrink-0",
        )}
      >
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-auto min-h-11 max-w-full self-start whitespace-normal sm:min-h-9"
          disabled={disabled}
          onClick={() => setDraft(null)}
        >
          <RotateCcw className="size-4 shrink-0" aria-hidden />
          {t("inheritNavigation")}
        </Button>
        <div className="flex flex-wrap justify-end gap-2 self-end">
          <Button
            type="button"
            variant="ghost"
            disabled={disabled || !dirty}
            onClick={() => setDraft(undefined)}
          >
            {t("discard")}
          </Button>
          <Button
            type="button"
            disabled={disabled || !dirty}
            onClick={() => {
              if (draft !== undefined) onSave(draft, () => setDraft(undefined));
            }}
          >
            {common("save")}
          </Button>
        </div>
      </div>
    </div>
  );
}

export function ConsoleNavigationSelection({
  value,
  allowed,
  disabled,
  onChange,
  showUnavailable = true,
}: {
  value: readonly string[] | null | undefined;
  allowed: readonly string[];
  disabled: boolean;
  onChange: (selection: string[]) => void;
  showUnavailable?: boolean;
}) {
  const id = useId();
  const nav = useTranslations("nav");
  const selection = allowed.filter((entry) => value == null || value.includes(entry));
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {(showUnavailable ? GROUPS : presentedNavigation(GROUPS, allowed)).map((group) => (
        <fieldset
          key={group.labelKey ?? "main"}
          disabled={disabled}
          className="min-w-0 rounded-xl border px-3 pb-2"
        >
          <legend className="text-muted-foreground px-1 text-xs font-medium">
            {nav(group.labelKey ?? "navigate")}
          </legend>
          <div>
            {group.items.map((item) => (
              <div
                key={item.labelKey}
                className="hover:bg-muted/40 flex min-h-11 items-center gap-3 rounded-lg px-2"
              >
                <Checkbox
                  id={`${id}-${item.labelKey}`}
                  checked={selection.includes(item.labelKey)}
                  disabled={disabled || !allowed.includes(item.labelKey)}
                  onCheckedChange={(checked) =>
                    onChange(
                      checked === true
                        ? [...selection, item.labelKey]
                        : selection.filter((entry) => entry !== item.labelKey),
                    )
                  }
                />
                <Label
                  htmlFor={`${id}-${item.labelKey}`}
                  className="flex min-h-11 flex-1 items-center gap-2 text-sm font-normal"
                >
                  <item.icon className="text-muted-foreground size-4" aria-hidden />
                  {nav(item.labelKey)}
                </Label>
              </div>
            ))}
          </div>
        </fieldset>
      ))}
    </div>
  );
}
