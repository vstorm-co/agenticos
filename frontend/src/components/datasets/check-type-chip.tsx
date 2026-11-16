import {
  Ban,
  Braces,
  Coins,
  Equal,
  ListChecks,
  Regex,
  Ruler,
  Scale,
  TextSearch,
  Timer,
  type LucideIcon,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { DatasetChip, type DatasetTone } from "./dataset-chip";
import { isKnownCheck, type CheckType } from "./case-form";

const CHECKS: Record<CheckType, { tone: DatasetTone; icon: LucideIcon }> = {
  contains: { tone: "blue", icon: TextSearch },
  not_contains: { tone: "red", icon: Ban },
  equals: { tone: "green", icon: Equal },
  regex: { tone: "purple", icon: Regex },
  json_schema: { tone: "purple", icon: Braces },
  max_cost_usd: { tone: "green", icon: Coins },
  max_latency_ms: { tone: "yellow", icon: Timer },
  length: { tone: "blue", icon: Ruler },
  judge: { tone: "purple", icon: Scale },
};

export function CheckTypeChip({ type }: { type: string }) {
  const t = useTranslations("datasets.checkTypes");
  return isKnownCheck(type) ? (
    <DatasetChip {...CHECKS[type]}>{t(type)}</DatasetChip>
  ) : (
    <DatasetChip tone="gray" icon={ListChecks}>
      {type}
    </DatasetChip>
  );
}
