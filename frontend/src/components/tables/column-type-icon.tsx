import {
  AlignLeft,
  Calendar,
  CalendarClock,
  CircleDot,
  Globe,
  Hash,
  Link2,
  ListChecks,
  type LucideIcon,
  ScanSearch,
  Sigma,
  Mail,
  Phone,
  SquareCheck,
  SquareFunction,
  Star,
  Type,
} from "lucide-react";

import type { ColumnTypeName } from "@/types/tables";
import { cn } from "@/lib/utils";

const ICON: Record<ColumnTypeName, LucideIcon> = {
  text: Type,
  long_text: AlignLeft,
  email: Mail,
  url: Globe,
  phone: Phone,
  number: Hash,
  integer: Hash,
  rating: Star,
  boolean: SquareCheck,
  date: Calendar,
  datetime: CalendarClock,
  single_select: CircleDot,
  multi_select: ListChecks,
  link: Link2,
  lookup: ScanSearch,
  rollup: Sigma,
  formula: SquareFunction,
};

/** What kind of values a column holds, at a glance: its type's icon beside its name. */
export function ColumnTypeIcon({ type, className }: { type: ColumnTypeName; className?: string }) {
  const Icon = ICON[type];
  return <Icon aria-hidden="true" className={cn("size-3.5 shrink-0 opacity-70", className)} />;
}

/** Whether a column holds numbers, read right-aligned so their digits line up. */
export function isNumeric(type: ColumnTypeName): boolean {
  return type === "number" || type === "integer" || type === "rollup";
}
