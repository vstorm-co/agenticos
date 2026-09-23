"use client";

import { useTranslations } from "next-intl";
import {
  Badge,
  Button,
  Checkbox,
  Label,
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui";
import type { OptionDef } from "@/types/tables";

/**
 * A `multi_select` cell: a popover with a checkbox per live option and a chip
 * summary on the trigger. No multi-select primitive exists yet in `ui/`, so
 * this stays scoped to `components/tables/` until a second consumer needs it.
 */
export function MultiSelectCell({
  id,
  options,
  value,
  onChange,
  disabled,
}: {
  id?: string;
  /** Live options only - an archived one a record still holds renders read-only elsewhere. */
  options: OptionDef[];
  value: string[];
  onChange: (value: string[]) => void;
  disabled?: boolean;
}) {
  const t = useTranslations("tables.cells");
  const live = options.filter((option) => !option.archived);
  const selected = live.filter((option) => value.includes(option.id));

  function toggle(optionId: string) {
    onChange(
      value.includes(optionId) ? value.filter((id) => id !== optionId) : [...value, optionId],
    );
  }

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          id={id}
          type="button"
          variant="outline"
          disabled={disabled}
          className="h-auto min-h-9 w-full flex-wrap justify-start gap-1 py-1.5"
        >
          {selected.length === 0 ? (
            <span className="text-muted-foreground">{t("noneSelected")}</span>
          ) : (
            selected.map((option) => (
              <Badge key={option.id} variant="secondary">
                {option.label}
              </Badge>
            ))
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-64 space-y-2" align="start">
        {live.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("noOptions")}</p>
        ) : (
          live.map((option) => (
            <div key={option.id} className="flex items-center gap-2">
              <Checkbox
                id={`${id}-${option.id}`}
                checked={value.includes(option.id)}
                onCheckedChange={() => toggle(option.id)}
                disabled={disabled}
              />
              <Label htmlFor={`${id}-${option.id}`} className="text-sm font-normal">
                {option.label}
              </Label>
            </div>
          ))
        )}
      </PopoverContent>
    </Popover>
  );
}
