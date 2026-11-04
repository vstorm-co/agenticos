import type { CSSProperties } from "react";

import type { Look } from "@/lib/appearance";
import { cn } from "@/lib/utils";

/**
 * What each look's thumbnail is painted in: the column, the page and a line of
 * ink, light and dark.
 *
 * An illustration of `looks.css`, not its tokens: the tokens live on `:root`,
 * where a thumbnail of another look cannot reach them, so a picture of the
 * standard look drawn while Midnight is on would otherwise be Midnight.
 */
const PREVIEW: Record<Look, { light: [string, string, string]; dark: [string, string, string] }> = {
  standard: {
    light: ["oklch(96.3% 0.002 265)", "oklch(97.8% 0.002 265)", "oklch(17.5% 0.004 265)"],
    dark: ["oklch(20.5% 0.0025 265)", "oklch(23.5% 0.0025 265)", "oklch(94.5% 0.003 265)"],
  },
  glass: {
    light: [
      "oklch(97% 0.004 265 / 0.45)",
      "oklch(98.5% 0.002 265 / 0.62)",
      "oklch(17.5% 0.004 265)",
    ],
    dark: ["oklch(22% 0.004 265 / 0.4)", "oklch(21% 0.004 265 / 0.62)", "oklch(94.5% 0.003 265)"],
  },
  graphite: {
    light: ["oklch(95.2% 0.004 75)", "oklch(97.2% 0.003 75)", "oklch(20% 0.008 75)"],
    dark: ["oklch(19.5% 0.004 75)", "oklch(22.5% 0.004 75)", "oklch(94% 0.005 75)"],
  },
  midnight: {
    light: ["oklch(95% 0.012 255)", "oklch(97.3% 0.008 255)", "oklch(20% 0.03 265)"],
    dark: ["oklch(14% 0.02 268)", "oklch(16.5% 0.022 268)", "oklch(95% 0.01 268)"],
  },
  paper: {
    light: ["oklch(94.5% 0.014 85)", "oklch(97% 0.012 85)", "oklch(25% 0.02 60)"],
    dark: ["oklch(20% 0.012 70)", "oklch(23% 0.013 70)", "oklch(93% 0.02 85)"],
  },
};

/** The soft backdrop a glass thumbnail sits on, as the glass console does in a browser. */
const GLASS_BACKDROP =
  "radial-gradient(circle at 0% 0%, var(--preview-glass-highlight), transparent 70%), var(--preview-glass-base)";

export function LookPreview({
  look,
  dark,
  className,
}: {
  look: Look;
  dark: boolean;
  className?: string;
}) {
  const [column, page, ink] = PREVIEW[look][dark ? "dark" : "light"];
  const backdrop: CSSProperties & {
    "--preview-glass-highlight"?: string;
    "--preview-glass-base"?: string;
  } =
    look === "glass"
      ? {
          backgroundImage: GLASS_BACKDROP,
          "--preview-glass-highlight": dark ? "oklch(42% 0.006 265)" : "white",
          "--preview-glass-base": dark ? "oklch(19% 0.004 265)" : "oklch(90% 0.004 265)",
        }
      : {};
  return (
    <svg
      aria-hidden
      viewBox="0 0 180 110"
      className={cn(
        "border-border aspect-[18/11] w-full overflow-hidden rounded-md border",
        className,
      )}
      style={backdrop}
    >
      <rect width="180" height="110" fill={page} />
      <rect width="44" height="110" fill={column} />
      {[10, 17, 24].map((x) => (
        <circle key={x} cx={x} cy="10" r="2" fill={ink} opacity="0.25" />
      ))}
      <rect x="8" y="24" width="27" height="4" rx="2" fill={ink} opacity="0.7" />
      <rect x="5" y="36" width="34" height="12" rx="3" fill={ink} opacity="0.1" />
      {[41, 57, 70, 83].map((y) => (
        <rect key={y} x="10" y={y} width="21" height="3" rx="1.5" fill={ink} opacity="0.4" />
      ))}
      <rect x="55" y="16" width="48" height="5" rx="2.5" fill={ink} opacity="0.8" />
      <rect x="55" y="26" width="77" height="3" rx="1.5" fill={ink} opacity="0.3" />
      {[55, 117].map((x) => (
        <g key={x}>
          <rect
            x={x}
            y="41"
            width="53"
            height="37"
            rx="5"
            fill={ink}
            fillOpacity="0.035"
            stroke={ink}
            strokeOpacity="0.12"
          />
          <rect x={x + 7} y="49" width="17" height="3" rx="1.5" fill={ink} opacity="0.35" />
          <rect x={x + 7} y="60" width="28" height="7" rx="2" fill={ink} opacity="0.65" />
        </g>
      ))}
      <rect x="55" y="88" width="115" height="13" rx="4" fill={ink} opacity="0.07" />
      <rect x="62" y="93" width="56" height="3" rx="1.5" fill={ink} opacity="0.25" />
    </svg>
  );
}
