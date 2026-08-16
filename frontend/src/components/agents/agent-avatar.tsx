"use client";

import { Bot } from "lucide-react";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui";
import { avatarPalette } from "@/lib/avatar-color";
import { cn } from "@/lib/utils";

const SIZES = {
  sm: "h-6 w-6 text-[10px]",
  md: "h-9 w-9 text-xs",
  lg: "h-14 w-14 text-base",
  xl: "h-20 w-20 text-lg",
} as const;

const ICON_SIZES = {
  sm: "h-3 w-3",
  md: "h-4 w-4",
  lg: "h-6 w-6",
  xl: "h-8 w-8",
} as const;

export interface AgentAvatarProps {
  agentId: string;
  name: string;
  /** False skips the request entirely and renders the fallback. */
  hasAvatar?: boolean;
  /** The chosen colour slot (1..10); null or absent derives it from the id. */
  colorSlot?: number | null;
  size?: keyof typeof SIZES;
  /**
   * Bumped to defeat the browser cache after an upload. Without it a replaced
   * picture keeps rendering as the old one until a hard reload, because the URL
   * did not change.
   */
  version?: number;
  className?: string;
}

/**
 * An agent's picture, everywhere an agent is named.
 *
 * The image is fetched from the API rather than from a public URL: reading it
 * goes through the same access check as reading the agent, so an avatar cannot
 * be used to confirm that an agent id exists.
 *
 * Initials rather than a generic robot whenever there is a name to take them
 * from - a wall of identical robot glyphs tells the reader nothing, and telling
 * two agents apart at a glance is the whole point of having a picture.
 */
export function AgentAvatar({
  agentId,
  name,
  hasAvatar = false,
  colorSlot,
  size = "md",
  version,
  className,
}: AgentAvatarProps) {
  const initials = agentInitials(name);
  const { bg, fg } = avatarPalette(agentId, colorSlot);
  return (
    <Avatar className={cn(SIZES[size], "border-border shrink-0 border", className)}>
      {hasAvatar && (
        <AvatarImage
          src={`/api/agents/${agentId}/avatar${version ? `?v=${version}` : ""}`}
          alt=""
        />
      )}
      <AvatarFallback className={cn(bg, fg, "font-semibold")}>
        {initials || <Bot className={ICON_SIZES[size]} aria-hidden />}
      </AvatarFallback>
    </Avatar>
  );
}

/** Up to two initials from an agent's name, or nothing usable to show. */
export function agentInitials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word[0])
    .join("")
    .toUpperCase();
}
