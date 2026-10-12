import { cn } from "@/lib/utils";

const SIZES = {
  sm: "h-6 w-6",
  lg: "h-14 w-14",
} as const;

/**
 * The Architect's own mark: a drafting compass standing as an "A".
 *
 * Neutral like the rest of the console - the foreground as the disc and the
 * page as the drawing - so it reads as the product's in light and dark and
 * never as one more agent's coloured face. An organization that gave its
 * Architect a picture sees that picture instead (`AssistantFace`).
 */
export function ArchitectMark({
  size,
  className,
}: {
  /** One of its own sizes; omitted where the caller sizes it through `className`. */
  size?: keyof typeof SIZES;
  className?: string;
}) {
  return (
    <span
      aria-hidden
      className={cn(
        "bg-foreground text-background inline-flex shrink-0 items-center justify-center rounded-full",
        size && SIZES[size],
        className,
      )}
    >
      <svg viewBox="0 0 24 24" fill="none" className="h-[62%] w-[62%]">
        {/* The legs, meeting at the hinge. */}
        <path
          d="M12 6.4 7.6 19M12 6.4 16.4 19"
          stroke="currentColor"
          strokeWidth="1.9"
          strokeLinecap="round"
        />
        {/* The arc the compass draws - the A's crossbar. */}
        <path
          d="M8.9 14.6c1.9 1.25 4.3 1.25 6.2 0"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
          opacity="0.75"
        />
        {/* The hinge, and the handle above it. */}
        <circle cx="12" cy="6" r="1.85" fill="currentColor" />
        <path d="M12 2.6v1.6" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" />
      </svg>
    </span>
  );
}
