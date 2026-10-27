"use client";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { avatarInitials, avatarPalette } from "@/lib/avatar-color";
import { cn } from "@/lib/utils";

const SIZES = {
  xs: "h-6 w-6 text-[11px]",
  sm: "h-7 w-7 text-[11px]",
  md: "h-9 w-9 text-xs",
  lg: "h-14 w-14 text-base",
  xl: "h-20 w-20 text-lg",
} as const;

export interface EntityAvatarProps {
  /** Stable id the fallback colour is derived from. */
  seed: string;
  /** Name or address - the accessible name, and the fallback initials. */
  name: string;
  /** The avatar endpoint. Omit for an entity that cannot have a picture. */
  imageSrc?: string;
  /**
   * Whether to fetch `imageSrc` at all. Defaults to whether one was given, so a
   * caller that knows the row has no uploaded picture (`hasImage={false}`) draws
   * initials without a request that would only 404.
   */
  hasImage?: boolean;
  /** The chosen colour slot (1..10); null or absent derives it from the seed. */
  colorSlot?: number | null;
  size?: keyof typeof SIZES;
  /** Hide from assistive tech when the name it stands for sits visibly beside it. */
  ariaHidden?: boolean;
  className?: string;
}

/**
 * A person's or organization's photo, with stable colour and readable initials
 * while it is absent or unavailable. Agents use their own generated faces, so
 * a conversation distinguishes the people from the agents at a glance.
 */
export function EntityAvatar({
  seed,
  name,
  imageSrc,
  hasImage,
  colorSlot,
  size = "md",
  ariaHidden,
  className,
}: EntityAvatarProps) {
  const showImage = (hasImage ?? imageSrc != null) && imageSrc != null;
  const { bg, fg } = avatarPalette(seed, colorSlot);
  return (
    <Avatar aria-hidden={ariaHidden} className={cn(SIZES[size], className, "rounded-full")}>
      {showImage && <AvatarImage src={imageSrc} alt="" />}
      <AvatarFallback className={cn(bg, fg, "font-semibold")}>
        {avatarInitials(name)}
      </AvatarFallback>
    </Avatar>
  );
}
