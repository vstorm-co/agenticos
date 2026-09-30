import { cn } from "@/lib/utils";
import type { ColumnDef } from "@/types/tables";

/**
 * Tints for a select column's options, by the option's place in the column - so
 * a value keeps its colour wherever it appears, and a new option takes the next.
 */
const TONES = [
  "bg-sky-500/10 text-sky-700 dark:text-sky-300",
  "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  "bg-amber-500/10 text-amber-700 dark:text-amber-300",
  "bg-violet-500/10 text-violet-700 dark:text-violet-300",
  "bg-rose-500/10 text-rose-700 dark:text-rose-300",
  "bg-muted text-foreground",
];

/** A select value as a chip: its option's label, tinted by where the option sits. */
export function OptionChip({ column, optionId }: { column: ColumnDef; optionId: string }) {
  const index = column.options.findIndex((option) => option.id === optionId);
  const option = index === -1 ? undefined : column.options[index];
  return (
    <span
      className={cn(
        "inline-flex max-w-full items-center truncate rounded-md px-1.5 py-0.5 text-xs font-medium",
        index === -1 ? "bg-muted text-muted-foreground" : TONES[index % TONES.length],
        option?.archived && "line-through opacity-70",
      )}
    >
      {option?.label ?? optionId}
    </span>
  );
}

/** A select cell's chips, or null when the column is not a select or holds nothing. */
export function selectChips(column: ColumnDef, value: unknown): React.ReactNode | null {
  if (column.type === "single_select" && typeof value === "string") {
    return <OptionChip column={column} optionId={value} />;
  }
  if (column.type === "multi_select" && Array.isArray(value) && value.length > 0) {
    return (
      <span className="flex flex-wrap gap-1">
        {value
          .filter((entry): entry is string => typeof entry === "string")
          .map((entry) => (
            <OptionChip key={entry} column={column} optionId={entry} />
          ))}
      </span>
    );
  }
  return null;
}
