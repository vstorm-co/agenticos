import type { OptionColor } from "@/types/tables";

export const OPTION_TONES: Record<OptionColor, string> = {
  gray: "bg-muted text-muted-foreground",
  blue: "bg-table-blue text-table-blue-foreground",
  green: "bg-table-green text-table-green-foreground",
  yellow: "bg-table-yellow text-table-yellow-foreground",
  purple: "bg-table-purple text-table-purple-foreground",
  red: "bg-table-red text-table-red-foreground",
};
