"use client";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { AvatarFace } from "@/components/ui/avatar-face";
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
  /** Stable id the face and the colour are derived from, so one entity keeps both. */
  seed: string;
  /** Name or address - the accessible name, and the initials for an organization. */
  name: string;
  /** The avatar endpoint. Omit for an entity that cannot have a picture. */
  imageSrc?: string;
  /**
   * Whether to fetch `imageSrc` at all. Defaults to whether one was given, so a
   * caller that knows the row has no uploaded picture (`hasImage={false}`) draws
   * the generated face without a request that would only 404.
   */
  hasImage?: boolean;
  /** The chosen colour slot (1..10); null or absent derives it from the seed. */
  colorSlot?: number | null;
  size?: keyof typeof SIZES;
  /**
   * What the fallback draws. A person gets a face; an organization gets its
   * initials, because a company is not somebody and a face on one reads as a
   * person who works there.
   */
  kind?: "person" | "org";
  /** Hide from assistive tech when the name it stands for sits visibly beside it. */
  ariaHidden?: boolean;
  className?: string;
}

/**
 * The picture that stands in for a person or an organization.
 *
 * When there is no uploaded picture the fallback is not a blank circle: a person
 * gets a face generated from their id, an organization two initials on a colour
 * keyed to the same id. Either way one entity looks the same on every screen and
 * a member list reads as designed. The image is rendered only when the caller
 * says there is one - Radix fetches an `<AvatarImage>` to detect its load state,
 * so drawing it unconditionally is a request per avatar-less row.
 */
export function EntityAvatar({
  seed,
  name,
  imageSrc,
  hasImage,
  colorSlot,
  size = "md",
  kind = "person",
  ariaHidden,
  className,
}: EntityAvatarProps) {
  const showImage = (hasImage ?? imageSrc != null) && imageSrc != null;
  const { bg, fg } = avatarPalette(seed, colorSlot);
  return (
    <Avatar aria-hidden={ariaHidden} className={cn(SIZES[size], className)}>
      {showImage && <AvatarImage src={imageSrc} alt="" />}
      {kind === "org" ? (
        <AvatarFallback className={cn(bg, fg, "font-semibold")}>
          {avatarInitials(name)}
        </AvatarFallback>
      ) : (
        // No fill of its own: the face brings its own disc, and a colour behind
        // it would show as a ring wherever the two discs disagree.
        <AvatarFallback className="bg-transparent">
          <AvatarFace seed={seed} colorSlot={colorSlot} />
        </AvatarFallback>
      )}
    </Avatar>
  );
}
