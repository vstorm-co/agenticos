import { Code2, Globe, TerminalSquare } from "lucide-react";
import { FaSlack } from "react-icons/fa6";
import { SiMattermost, SiTelegram } from "react-icons/si";

import { cn } from "@/lib/utils";

/**
 * One mark per `RunSurface` value - the single mapping the run table and the
 * surface filter both draw from, so a surface never wears two faces (#144's
 * rule, applied to surfaces).
 *
 * The messaging channels get their brand marks, the same components the
 * channels list draws, monochrome `currentColor` like every brand mark in the
 * console. The console's own surfaces get glyphs: the web chat a globe, the
 * embedded widget a code tag, the HTTP API a terminal.
 */
const MARKS = {
  web: Globe,
  embed: Code2,
  api: TerminalSquare,
  slack: FaSlack,
  telegram: SiTelegram,
  mattermost: SiMattermost,
} as const;

/**
 * The mark alone, decorative beside its own name.
 *
 * Callers render the surface name next to it, which is what carries the fact
 * for a screen reader - so the icon is `aria-hidden`, never a second, redundant
 * announcement of the same word.
 */
export function SurfaceIcon({ surface, className }: { surface: string; className?: string }) {
  const Mark = MARKS[surface as keyof typeof MARKS];
  if (Mark === undefined) return null;
  return <Mark className={cn("h-3.5 w-3.5 shrink-0", className)} aria-hidden />;
}
