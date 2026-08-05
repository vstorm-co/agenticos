"use client";

import {
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import type { DelegationMode } from "@/types/agents";
import { useTranslations } from "next-intl";

/** The option standing for "no override", which Radix cannot spell as `""`. */
const FOLLOW = "__follow__";

/**
 * The three modes, in the order they are worth reaching for.
 *
 * `words` is the catalog key for the mode's name; its sentence is the same key
 * plus `Detail`, the way the workspace's backends and scopes are keyed.
 */
const MODES: { id: DelegationMode; words: string }[] = [
  { id: "sync", words: "delegationModeSync" },
  { id: "async", words: "delegationModeAsync" },
  { id: "auto", words: "delegationModeAuto" },
];

interface DelegationModeFieldProps {
  id: string;
  /** `null` follows the capability's own `mode`. */
  value: DelegationMode | null;
  onChange: (mode: DelegationMode | null) => void;
  disabled?: boolean;
}

/**
 * How one delegate hands control back, when it differs from the policy.
 *
 * Its own component because both kinds of subagent carry the same override and
 * the words are the part worth not writing twice: "async" means the parent
 * carries on while the delegate works, which is a real thing to want for one slow
 * specialist and a bad default for everything else.
 *
 * Following the policy is stored as the absence of a value rather than as a
 * fourth mode, so changing the policy moves every delegate that never disagreed
 * with it.
 */
export function DelegationModeField({ id, value, onChange, disabled }: DelegationModeFieldProps) {
  const t = useTranslations("agents");
  return (
    <div className="max-w-xs space-y-1.5">
      <Label htmlFor={id}>{t("delegationModeLabel")}</Label>
      <Select
        value={value ?? FOLLOW}
        disabled={disabled}
        onValueChange={(next) => onChange(next === FOLLOW ? null : (next as DelegationMode))}
      >
        <SelectTrigger id={id}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={FOLLOW}>{t("delegationModeFollow")}</SelectItem>
          {MODES.map((mode) => (
            <SelectItem key={mode.id} value={mode.id}>
              {t(mode.words)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <p className="text-muted-foreground text-xs">
        {t(`${MODES.find((mode) => mode.id === value)?.words ?? "delegationModeFollow"}Detail`)}
      </p>
    </div>
  );
}
