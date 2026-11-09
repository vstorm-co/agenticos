import type { ReactNode } from "react";
import { FilePenLine, FileUp, MessagesSquare, Sparkles, type LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";

import { OPTION_TONES } from "@/lib/table-option-colors";
import { cn } from "@/lib/utils";
import type { CaseSource } from "@/types/datasets";

export type DatasetTone = keyof typeof OPTION_TONES;

/** The same option colours and shape as Virtual Tables. */
export function DatasetChip({
  tone,
  icon: Icon,
  children,
  className,
}: {
  tone: DatasetTone;
  icon?: LucideIcon;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex max-w-full min-w-0 items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-medium",
        OPTION_TONES[tone],
        className,
      )}
    >
      {Icon && <Icon className="size-3 shrink-0" aria-hidden />}
      <span className="truncate">{children}</span>
    </span>
  );
}

const SOURCES: Record<CaseSource, { tone: DatasetTone; icon: LucideIcon }> = {
  manual: { tone: "blue", icon: FilePenLine },
  import: { tone: "green", icon: FileUp },
  conversation: { tone: "yellow", icon: MessagesSquare },
  synthetic: { tone: "purple", icon: Sparkles },
};

export function CaseSourceChip({ source }: { source: CaseSource }) {
  const t = useTranslations("datasets");
  return <DatasetChip {...SOURCES[source]}>{t(`source.${source}`)}</DatasetChip>;
}

const TAG_TONES: DatasetTone[] = ["blue", "purple", "green", "yellow"];

/** A tag keeps its colour across cases and pages. */
export function CaseTag({ tag }: { tag: string }) {
  const hash = Array.from(tag).reduce((sum, char) => sum + (char.codePointAt(0) ?? 0), 0);
  return <DatasetChip tone={TAG_TONES[hash % TAG_TONES.length] ?? "gray"}>{tag}</DatasetChip>;
}
