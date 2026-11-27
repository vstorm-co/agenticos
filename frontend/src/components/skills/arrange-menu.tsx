"use client";

import { ChevronDown, Rows3 } from "lucide-react";
import { useTranslations } from "next-intl";

import { FILTER_CONTROL } from "@/components/ui/control-styles";
import { cn } from "@/lib/utils";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui";

const ARRANGEMENTS = ["agent", "origin", "category", "none"] as const;

/** How the Skills page lays its library out; `none` is the plain paged grid. */
export type Arrangement = (typeof ARRANGEMENTS)[number];

/** The arrangement an address names, by agent when it names none or one we do not know. */
export function parseArrangement(value: string | null): Arrangement {
  return ARRANGEMENTS.find((entry) => entry === value) ?? "agent";
}

/**
 * Pick how the skills are laid out.
 *
 * "Arrange", not "group": a group is a department in this product, and the
 * department filter sits right beside this control. Arranging only orders
 * what the reader already sees.
 */
export function ArrangeMenu({
  value,
  onChange,
}: {
  value: Arrangement;
  onChange: (next: Arrangement) => void;
}) {
  const t = useTranslations("pages.skills");
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="outline"
          className={cn(
            FILTER_CONTROL,
            // An icon alone on a phone, like the Filters button beside it, so the
            // search keeps the room it needs on one row.
            "touch:min-h-11 touch:min-w-11 shrink-0 touch-manipulation max-sm:min-w-11 max-sm:px-2.5",
          )}
          title={t("arrangeBy")}
          data-tour="skills-arrange"
        >
          <Rows3 className="size-4 shrink-0 opacity-70" strokeWidth={1.75} aria-hidden />
          <span className="max-sm:sr-only">{t(`arrange.${value}`)}</span>
          <ChevronDown className="h-4 w-4 opacity-60 max-sm:hidden" aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        <DropdownMenuLabel>{t("arrangeBy")}</DropdownMenuLabel>
        <DropdownMenuRadioGroup
          value={value}
          onValueChange={(next) => onChange(parseArrangement(next))}
        >
          {ARRANGEMENTS.map((entry) => (
            <DropdownMenuRadioItem key={entry} value={entry}>
              {t(`arrange.${entry}`)}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
