"use client";

import {
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import type { UsageReporting } from "@/types/channels";
import { useTranslations } from "next-intl";

/**
 * How talkative this agent is here about what a turn cost.
 *
 * Under the binding rather than on the Channels page, where it started. Whether
 * an answer carries a cost footer is part of what this agent says on this
 * surface - the same class of decision as the extra instructions beside it -
 * and on the bot it was an operator's setting, in a table of servers and
 * tokens, next to nothing else about the agent.
 *
 * Nothing is unmeasured. `off` means the bot does not *say* it; the report is
 * written either way, because "the bot went quiet" is a question somebody asks
 * days later and a report that was never taken is no help then.
 *
 * Saved on the choice rather than behind a button: it is one value out of four,
 * and there is no half-typed state to protect.
 */
export function ExposureCostReporting({
  exposureId,
  value,
  disabled,
  onChange,
}: {
  /** Scopes the control's id, so two bindings on one page do not share a label. */
  exposureId: string;
  value: UsageReporting;
  disabled: boolean;
  onChange: (usageReporting: UsageReporting) => void;
}) {
  const t = useTranslations("agents");
  const id = `cost-reporting-${exposureId}`;
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id} className="text-xs font-medium">
        {t("costReporting")}
      </Label>
      <Select
        value={value.mode}
        disabled={disabled}
        onValueChange={(mode) => onChange({ ...value, mode: mode as UsageReporting["mode"] })}
      >
        <SelectTrigger id={id} className="w-full">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="off">{t("usageLogOnly")}</SelectItem>
          <SelectItem value="near_limit">{t("usageNearLimit")}</SelectItem>
          <SelectItem value="every_n">
            {t("usageEveryNMessages", { count: value.every_n })}
          </SelectItem>
          <SelectItem value="always">{t("usageEveryReply")}</SelectItem>
        </SelectContent>
      </Select>
      <p className="text-muted-foreground text-xs">{t("costReportingHint")}</p>
    </div>
  );
}
