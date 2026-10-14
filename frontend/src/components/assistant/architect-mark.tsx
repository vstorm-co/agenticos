import { cn } from "@/lib/utils";

const SIZES = {
  sm: "h-6 w-6",
  lg: "h-14 w-14",
} as const;

/** The blueprint's own blue, the one colour the Architect wears in every theme. */
const BLUEPRINT = "#2557d6";

/**
 * The Architect's own mark: a blueprint sheet with the agents' two pill eyes.
 *
 * The plan it draws for you, and a member of the same family as every agent's
 * face - the eyes are the ones the avatars wear - in the one colour that says
 * "the platform's own helper" beside agents somebody built. The same mark in
 * light and dark, because a blueprint is blue on either. An organization that
 * gave its Architect a picture sees that picture instead (`AssistantFace`).
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
        "inline-flex shrink-0 overflow-hidden rounded-full",
        size && SIZES[size],
        className,
      )}
    >
      <svg viewBox="0 0 24 24" className="h-full w-full">
        <circle cx="12" cy="12" r="12" fill={BLUEPRINT} />
        {/* The drafting grid, faint, so it reads as paper rather than a pattern. */}
        <g stroke="#fff" strokeOpacity="0.24" strokeWidth="0.45">
          <path d="M0 7.5h24M0 12h24M0 16.5h24M7.5 0v24M12 0v24M16.5 0v24" />
        </g>
        {/* The eyes every agent in the console wears. */}
        <rect x="8.4" y="8.9" width="2.3" height="4.9" rx="1.15" fill="#fff" />
        <rect x="13.3" y="8.9" width="2.3" height="4.9" rx="1.15" fill="#fff" />
      </svg>
    </span>
  );
}
