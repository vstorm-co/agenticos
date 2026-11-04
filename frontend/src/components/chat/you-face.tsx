"use client";

import { User } from "lucide-react";

import { EntityAvatar } from "@/components/ui/entity-avatar";
import { useAuthStore } from "@/stores";

/**
 * The reader's photo or initials in a transcript, or a plain glyph for a
 * signed-out reader of a shared transcript. Sized by the circle it is put in.
 *
 * Through `EntityAvatar`, as the sidebar draws the same person: a picture that
 * fails to load falls back to the initials. A bare image left an empty
 * circle beside "You" whenever the stored file was missing.
 */
export function YouFace() {
  const { user, avatarVersion } = useAuthStore();
  if (!user) return <User className="h-4 w-4" />;
  return (
    <EntityAvatar
      seed={user.id}
      name={user.full_name || user.email}
      imageSrc={`/api/users/avatar/${user.id}?v=${avatarVersion}`}
      hasImage={!!user.avatar_url}
      colorSlot={user.avatar_color}
      className="h-full w-full"
      ariaHidden
    />
  );
}
