"use client";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui";
import { AvatarFace } from "@/components/ui/avatar-face";
import { cn } from "@/lib/utils";

const SIZES = {
  sm: "h-6 w-6 text-[10px]",
  md: "h-9 w-9 text-xs",
  lg: "h-14 w-14 text-base",
  xl: "h-20 w-20 text-lg",
} as const;

export interface AgentAvatarProps {
  /** Which agent's uploaded picture to fetch, when it has one. */
  agentId: string;
  /**
   * The handle the generated face is drawn from.
   *
   * Not the id, which is what it used to be, and not the name. The handle is
   * derived from the name and then frozen, so the face can be shown before the
   * agent exists - the creation dialog draws it while somebody is still typing -
   * and renaming still does not hand an agent somebody else's face. Required
   * rather than optional: a fallback to the id would give one agent two faces
   * depending on which screen you were looking at.
   */
  slug: string;
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
  /**
   * Draws the face mid-thought while the agent is answering. Only worth setting
   * where a turn is actually in flight - it costs inline SVG per face.
   */
  thinking?: boolean;
  className?: string;
}

/**
 * An agent's picture, everywhere an agent is named.
 *
 * The image is fetched from the API rather than from a public URL: reading it
 * goes through the same access check as reading the agent, so an avatar cannot
 * be used to confirm that an agent id exists.
 *
 * Without one, a face generated from the agent's handle - not a generic robot
 * glyph. A wall of identical robots tells the reader nothing, and telling two
 * agents apart at a glance is the whole point of having a picture. The handle
 * rather than the name, because it is frozen at creation: renaming an agent does
 * not hand it somebody else's face, and the face can be drawn before the agent
 * exists at all.
 */
export function AgentAvatar({
  agentId,
  slug,
  hasAvatar = false,
  colorSlot,
  size = "md",
  version,
  thinking,
  className,
}: AgentAvatarProps) {
  return (
    <Avatar className={cn(SIZES[size], "border-border shrink-0 border", className)}>
      {hasAvatar && (
        <AvatarImage
          src={`/api/agents/${agentId}/avatar${version ? `?v=${version}` : ""}`}
          alt=""
        />
      )}
      {/* No fill of its own: the face brings its own disc, and a colour behind
          it would show as a ring wherever the two discs disagree. */}
      <AvatarFallback className="bg-transparent">
        <AvatarFace seed={slug} colorSlot={colorSlot} thinking={thinking} />
      </AvatarFallback>
    </Avatar>
  );
}
