import { OPTION_TONES } from "@/lib/table-option-colors";
import { cn } from "@/lib/utils";
import { PrincipalBadges } from "./principal-cell";
import { PRINCIPAL_COLUMN_TYPES, type ColumnDef } from "@/types/tables";

/**
 * Tints for a select column's options, by the option's place in the column - so
 * a value keeps its colour wherever it appears, and a new option takes the next.
 */
const TONES = [
  OPTION_TONES.blue,
  OPTION_TONES.green,
  OPTION_TONES.yellow,
  OPTION_TONES.purple,
  OPTION_TONES.red,
  OPTION_TONES.gray,
];

/** A select value as a chip: its option's label, tinted by where the option sits. */
export function OptionChip({
  column,
  optionId,
}: {
  /** Only its options are read: where one sits gives its tint. */
  column: Pick<ColumnDef, "options">;
  optionId: string;
}) {
  const index = column.options.findIndex((option) => option.id === optionId);
  const option = index === -1 ? undefined : column.options[index];
  return (
    <span
      className={cn(
        "inline-flex max-w-full items-center truncate rounded-md px-1.5 py-0.5 text-xs font-medium",
        option?.color
          ? OPTION_TONES[option.color]
          : index === -1
            ? "bg-muted text-muted-foreground"
            : TONES[index % TONES.length],
        option?.archived && "line-through opacity-70",
      )}
    >
      {option?.label ?? optionId}
    </span>
  );
}

/** A select cell's chips, or null when the column is not a select or holds nothing. */
export function selectChips(column: ColumnDef, value: unknown): React.ReactNode | null {
  if (
    PRINCIPAL_COLUMN_TYPES.has(column.type) &&
    (typeof value === "string" ||
      (Array.isArray(value) && value.every((item): item is string => typeof item === "string")))
  ) {
    return (
      <PrincipalBadges
        value={value}
        kind={column.type === "user" || column.type === "multi_user" ? "user" : "agent"}
      />
    );
  }
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
