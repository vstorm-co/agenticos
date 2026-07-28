import { cn } from "@/lib/utils";

interface MonogramProps {
  /** What the thing is called. The first character is what gets drawn. */
  label: string;
  className?: string;
}

/**
 * The stand-in for something with no brand mark.
 *
 * Every icon set is a finite list and this platform's catalogs are not: a
 * deployment gains a model provider whenever Pydantic AI does, and an MCP
 * server the moment somebody pastes a URL. "No mark" is therefore the normal
 * case rather than the error case, and it has to look like a decision.
 *
 * A bordered initial in the same square the logos occupy reads as deliberate. A
 * broken `<img>` or a blank gap does not - and neither does one generic icon
 * repeated down the column, which is worse than nothing because it removes the
 * only reason to have icons in a list: telling the rows apart at a glance.
 *
 * Always decorative. Every caller prints the name beside it, and a mark that
 * named itself would make a screen reader say it twice.
 */
export function Monogram({ label, className }: MonogramProps) {
  return (
    <span
      aria-hidden
      className={cn(
        "border-border text-muted-foreground flex items-center justify-center rounded-[3px] border text-[10px] font-medium uppercase",
        className,
      )}
    >
      {label.slice(0, 1)}
    </span>
  );
}
