"use client";

import { useTranslations } from "next-intl";
import {
  Button,
  Checkbox,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { ListFilters } from "@/components/ui/list-filters";
import type { MemoryClaimFilters } from "@/lib/memory-api";

const KINDS = ["all", "fact", "preference", "decision"] as const;
export type Kind = "all" | NonNullable<MemoryClaimFilters["kind"]>;
export type Scope = "all" | NonNullable<MemoryClaimFilters["scope"]>;

export function ClaimFilters({
  kind,
  scope,
  history,
  onKindChange,
  onScopeChange,
  onHistoryChange,
}: {
  kind: Kind;
  scope: Scope;
  history: boolean;
  onKindChange: (kind: Kind) => void;
  onScopeChange: (scope: Scope) => void;
  onHistoryChange: (history: boolean) => void;
}) {
  const t = useTranslations("pages.memory.claims");
  const view = useTranslations("pages.memory.browser");
  return (
    <>
      <div className="hidden flex-wrap gap-0.5 lg:flex" role="group" aria-label={view("typeLabel")}>
        {KINDS.map((value) => (
          <Button
            key={value}
            variant={kind === value ? "secondary" : "ghost"}
            size="sm"
            aria-pressed={kind === value}
            onClick={() => onKindChange(value)}
          >
            {view(`kind.${value}`)}
          </Button>
        ))}
      </div>
      <div className="min-w-0 flex-1 sm:max-w-40 lg:hidden">
        <Select
          value={kind}
          onValueChange={(value) => {
            const next = KINDS.find((entry) => entry === value);
            if (next) onKindChange(next);
          }}
        >
          <SelectTrigger aria-label={view("typeLabel")}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {KINDS.map((value) => (
              <SelectItem key={value} value={value}>
                {view(`kind.${value}`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="contents">
        <ListFilters active={Number(scope !== "all") + Number(history)} compact>
          <div className="flex w-full flex-wrap items-center gap-3 pt-2">
            <Select
              value={scope}
              onValueChange={(value) => {
                if (value === "all" || value === "profile" || value === "agent")
                  onScopeChange(value);
              }}
            >
              <SelectTrigger className="h-8 w-44 text-xs" aria-label={view("scopeLabel")}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(["all", "profile", "agent"] as const).map((value) => (
                  <SelectItem key={value} value={value}>
                    {view(`scope.${value}`)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <label className="text-muted-foreground flex items-center gap-2 text-xs">
              <Checkbox
                checked={history}
                onCheckedChange={(next) => onHistoryChange(next === true)}
              />
              {t("showHistory")}
            </label>
          </div>
        </ListFilters>
      </div>
    </>
  );
}
