"use client";

import type { ReactNode } from "react";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { avatarInitials, avatarPalette } from "@/lib/avatar-color";
import { cn } from "@/lib/utils";

const SIZES = {
  xs: "h-6 w-6 text-[10px]",
  sm: "h-7 w-7 text-[10px]",
  md: "h-9 w-9 text-xs",
  lg: "h-14 w-14 text-base",
  xl: "h-20 w-20 text-lg",
} as const;

export interface EntityAvatarProps {
  /** Stable id the colour is derived from, so one entity keeps its colour. */
  seed: string;
  /** Name or address the initials are taken from. */
  name: string;
  /** The avatar endpoint. Omit for an entity that cannot have a picture. */
  imageSrc?: string;
  /**
   * Whether to fetch `imageSrc` at all. Defaults to whether one was given, so a
   * caller that knows the row has no uploaded picture (`hasImage={false}`) draws
   * the coloured initials without a request that would only 404.
   */
  hasImage?: boolean;
  size?: keyof typeof SIZES;
  /** A glyph for an entity with no usable name, in place of empty initials. */
  fallbackIcon?: ReactNode;
  /** Hide from assistive tech when the name it stands for sits visibly beside it. */
  ariaHidden?: boolean;
  className?: string;
}

/**
 * The picture that stands in for a person, an organization or an agent.
 *
 * When there is no uploaded picture the fallback is not a blank circle: two
 * initials on a colour keyed to the id, so a member list reads as designed and
 * one entity wears the same colour on every screen. The image is rendered only
 * when the caller says there is one - Radix fetches an `<AvatarImage>` to detect
 * its load state, so drawing it unconditionally is a request per avatar-less row.
 */
export function EntityAvatar({
  seed,
  name,
  imageSrc,
  hasImage,
  size = "md",
  fallbackIcon,
  ariaHidden,
  className,
}: EntityAvatarProps) {
  const initials = avatarInitials(name);
  const { bg, fg } = avatarPalette(seed);
  const showImage = (hasImage ?? imageSrc != null) && imageSrc != null;
  return (
    <Avatar aria-hidden={ariaHidden} className={cn(SIZES[size], className)}>
      {showImage && <AvatarImage src={imageSrc} alt="" />}
      <AvatarFallback className={cn(bg, fg, "font-semibold")}>
        {initials || fallbackIcon}
      </AvatarFallback>
    </Avatar>
  );
}
