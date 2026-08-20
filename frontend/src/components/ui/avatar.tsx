"use client";

import * as React from "react";
import * as AvatarPrimitive from "@radix-ui/react-avatar";
import { cn } from "@/lib/utils";

const Avatar = React.forwardRef<
  React.ComponentRef<typeof AvatarPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof AvatarPrimitive.Root>
>(({ className, ...props }, ref) => (
  <AvatarPrimitive.Root
    ref={ref}
    className={cn(
      // The type scale lives here, on the same element as the diameter, because
      // a font-size on the fallback would beat the one it inherits: every
      // circle drew 12px initials whatever its size, so `text-[10px]` in a
      // 16px circle rendered as an unreadable smudge and `text-lg` in an 80px
      // one as two small letters in a lot of colour.
      "relative flex h-10 w-10 shrink-0 overflow-hidden rounded-full text-xs",
      className,
    )}
    {...props}
  />
));
Avatar.displayName = AvatarPrimitive.Root.displayName;

const AvatarImage = React.forwardRef<
  React.ComponentRef<typeof AvatarPrimitive.Image>,
  React.ComponentPropsWithoutRef<typeof AvatarPrimitive.Image>
>(({ className, ...props }, ref) => (
  <AvatarPrimitive.Image
    ref={ref}
    className={cn("aspect-square h-full w-full", className)}
    {...props}
  />
));
AvatarImage.displayName = AvatarPrimitive.Image.displayName;

const AvatarFallback = React.forwardRef<
  React.ComponentRef<typeof AvatarPrimitive.Fallback>,
  React.ComponentPropsWithoutRef<typeof AvatarPrimitive.Fallback>
>(({ className, ...props }, ref) => (
  <AvatarPrimitive.Fallback
    ref={ref}
    className={cn(
      // High-contrast neutral fallback - initials need to be readable on
      // every theme regardless of the brand color (low-saturation greens
      // washed out the previous bg-muted/text-brand combo). No font-size:
      // the root's is inherited, and one here would override it.
      "bg-foreground/10 text-foreground flex h-full w-full items-center justify-center rounded-full font-semibold",
      className,
    )}
    {...props}
  />
));
AvatarFallback.displayName = AvatarPrimitive.Fallback.displayName;

export { Avatar, AvatarImage, AvatarFallback };
