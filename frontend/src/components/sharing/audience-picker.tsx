"use client";

import { Building2, Lock, Users } from "lucide-react";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";
import type { AudiencePayload } from "@/types/sharing";
import { AudienceSearch } from "./audience-search";

/** Who a new resource reaches: the whole organization, its creator, or chosen groups and people. */
export interface Audience {
  mode: "org" | "private" | "chosen";
  group_ids: string[];
  user_ids: string[];
}

export const EVERYONE: Audience = { mode: "org", group_ids: [], user_ids: [] };

/**
 * What a create request sends for an audience.
 *
 * "Chosen" with nobody picked yet sends the whole organization: a choice half made
 * is not a reason to hide the new thing from everyone.
 */
export function audiencePayload(audience: Audience): AudiencePayload {
  if (audience.mode === "chosen" && audience.group_ids.length + audience.user_ids.length > 0) {
    return { visibility: "private", group_ids: audience.group_ids, user_ids: audience.user_ids };
  }
  return {
    visibility: audience.mode === "private" ? "private" : "org",
    group_ids: [],
    user_ids: [],
  };
}

/**
 * The one control that decides who a new agent, skill, knowledge base, context
 * file or MCP server reaches (#2072).
 *
 * The organization by default, because a company's agents and knowledge are the
 * company's; narrowed to the creator, or to departments and people found by
 * searching, which the server turns into a private resource shared with each.
 * `withOnlyMe` is off where "only me" has its own, clearer control - an MCP
 * server connected with the person's own account.
 */
export function AudiencePicker({
  value,
  onChange,
  disabled,
  withOnlyMe = true,
}: {
  value: Audience;
  onChange: (audience: Audience) => void;
  disabled?: boolean;
  withOnlyMe?: boolean;
}) {
  const t = useTranslations("audience");

  const options = [
    { mode: "org", icon: Building2, label: t("everyone"), hint: t("everyoneHint") },
    ...(withOnlyMe
      ? [{ mode: "private", icon: Lock, label: t("onlyMe"), hint: t("onlyMeHint") } as const]
      : []),
    { mode: "chosen", icon: Users, label: t("chosen"), hint: t("chosenHint") },
  ] as const;

  return (
    <div className="space-y-2">
      <div
        role="radiogroup"
        aria-label={t("label")}
        className={cn("grid gap-2", withOnlyMe ? "sm:grid-cols-3" : "sm:grid-cols-2")}
      >
        {options.map((option) => (
          <button
            key={option.mode}
            type="button"
            role="radio"
            aria-checked={value.mode === option.mode}
            disabled={disabled}
            onClick={() =>
              onChange(
                option.mode === "chosen"
                  ? { ...value, mode: "chosen" }
                  : { mode: option.mode, group_ids: [], user_ids: [] },
              )
            }
            className={cn(
              "flex flex-col items-start gap-1 rounded-lg border p-3 text-left transition-colors disabled:opacity-50",
              value.mode === option.mode ? "border-foreground/40 bg-accent" : "hover:bg-accent/50",
            )}
          >
            <span className="flex items-center gap-1.5 text-sm font-medium">
              <option.icon className="h-4 w-4" aria-hidden />
              {option.label}
            </span>
            <span className="text-muted-foreground text-xs">{option.hint}</span>
          </button>
        ))}
      </div>
      {value.mode === "chosen" && (
        <AudienceSearch value={value} onChange={onChange} disabled={disabled} />
      )}
    </div>
  );
}
