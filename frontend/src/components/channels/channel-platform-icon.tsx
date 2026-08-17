import { MessageSquare } from "lucide-react";

import { brandMark } from "@/components/icons/brand-icon";
import { cn } from "@/lib/utils";
import type { ChannelPlatform } from "@/types/channels";

const MARKS = {
  slack: brandMark("slack"),
  telegram: brandMark("telegram"),
  mattermost: brandMark("mattermost"),
} as const;

/**
 * The chat platform's own mark, in a tile.
 *
 * The same reason the vault draws a provider logo rather than a row of
 * identical text: a channels list is scanned, not read, and "which of these is
 * the Slack one" is the first question asked of it. Monochrome `currentColor`
 * like every other brand mark in the console - a column where Slack is four
 * colours and Mattermost is ink reads as two different products.
 *
 * A platform this build has no mark for falls back to a speech bubble rather
 * than to nothing: the tile is what gives the row its left edge, and a missing
 * one collapses the whole column by a tile's width.
 */
export function ChannelPlatformIcon({
  platform,
  className,
}: {
  platform: ChannelPlatform | string;
  className?: string;
}) {
  const Mark = MARKS[platform as ChannelPlatform] ?? MessageSquare;
  return (
    <span
      className={cn(
        "bg-muted text-muted-foreground flex h-8 w-8 shrink-0 items-center justify-center rounded-lg",
        className,
      )}
    >
      <Mark className="h-4 w-4" aria-hidden />
    </span>
  );
}
