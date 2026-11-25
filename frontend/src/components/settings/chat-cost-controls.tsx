"use client";

import { useId } from "react";
import { useTranslations } from "next-intl";
import {
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import type { ChatCostPolicy, ChatCostVisibility } from "@/lib/console-experience-api";

const POLICIES: readonly ChatCostVisibility[] = ["everyone", "spend_privileged", "nobody"];

export function OrganizationChatCostControl({
  value,
  disabled,
  onChange,
}: {
  value: ChatCostVisibility;
  disabled: boolean;
  onChange: (value: ChatCostVisibility) => void;
}) {
  const t = useTranslations("consoleExperience.costs");
  const id = useId();
  return (
    <div className="space-y-2" data-tour="organization-chat-costs">
      <Label htmlFor={id}>{t("audience")}</Label>
      <Select
        value={value}
        disabled={disabled}
        onValueChange={(next) => {
          const policy = POLICIES.find((item) => item === next);
          if (policy) onChange(policy);
        }}
      >
        <SelectTrigger id={id}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {POLICIES.map((policy) => (
            <SelectItem key={policy} value={policy}>
              {t(policy)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

export function PersonalChatCostControl({
  policy,
  disabled,
  onChange,
}: {
  policy: ChatCostPolicy;
  disabled: boolean;
  onChange: (value: boolean | null) => void;
}) {
  const t = useTranslations("consoleExperience");
  const id = useId();
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{t("costs.personalLabel")}</Label>
      <Select
        value={policy.preference == null ? "inherit" : policy.preference ? "show" : "hide"}
        disabled={disabled || !policy.permitted}
        onValueChange={(next) => onChange(next === "inherit" ? null : next === "show")}
      >
        <SelectTrigger id={id} aria-describedby={`${id}-hint`}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="inherit">
            {t(policy.permitted ? "inheritShown" : "inheritHidden")}
          </SelectItem>
          <SelectItem value="show">{t("show")}</SelectItem>
          <SelectItem value="hide">{t("hide")}</SelectItem>
        </SelectContent>
      </Select>
      <p id={`${id}-hint`} className="text-muted-foreground text-xs leading-5">
        {t(policy.permitted ? "costs.personalHint" : "costs.restricted")}
      </p>
    </div>
  );
}
