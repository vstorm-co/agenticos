"use client";

import { useId, useState, useEffect, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { Button, Checkbox, Label } from "@/components/ui";
import { useUnsavedChanges } from "@/hooks/use-unsaved-changes";
import { cn } from "@/lib/utils";
import { NAV_GROUPS, presentedNavigation } from "@/lib/nav-sections";

const GROUPS = NAV_GROUPS.filter((group) => !group.adminOnly && !group.switcherOnly);

/** Draft a complete selection before replacing this one presentation field. */
export function ConsoleNavigationControls({
  value,
  allowed,
  simple,
  disabled,
  onSave,
  preview,
  onDirtyChange,
  showUnavailable = true,
}: {
  value: readonly string[] | null | undefined;
  allowed: readonly string[];
  simple?: readonly string[];
  disabled: boolean;
  onSave: (value: string[] | null, onSaved: () => void) => void;
  preview?: (selection: readonly string[]) => ReactNode;
  onDirtyChange?: (dirty: boolean) => void;
  showUnavailable?: boolean;
}) {
  const id = useId();
  const t = useTranslations("consoleExperience.presentation");
  const common = useTranslations("common");
  const [draft, setDraft] = useState<string[] | null | undefined>(undefined);
  const selected = (draft === undefined ? value : draft) ?? allowed;
  const selection = allowed.filter((entry) => selected.includes(entry));
  const dirty = draft !== undefined;
  useEffect(() => {
    onDirtyChange?.(dirty);
  }, [dirty, onDirtyChange]);
  useUnsavedChanges(id, { dirty, discard: () => setDraft(undefined) });
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {simple && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={disabled}
            onClick={() => setDraft(allowed.filter((entry) => simple.includes(entry)))}
          >
            {t("simple")}
          </Button>
        )}
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={disabled}
          onClick={() => setDraft(null)}
        >
          {t("inheritNavigation")}
        </Button>
      </div>
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
      <div className="flex flex-wrap justify-end gap-2 border-t pt-4">
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
        <fieldset key={group.labelKey ?? "main"} disabled={disabled}>
          <legend className="text-muted-foreground mb-1 text-xs font-medium">
            {nav(group.labelKey ?? "navigate")}
          </legend>
          <div>
            {group.items.map((item) => (
              <div key={item.labelKey} className="flex min-h-11 items-center gap-3">
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
