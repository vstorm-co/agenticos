"use client";

import Image from "next/image";
import { User } from "lucide-react";

import { AvatarFace } from "@/components/ui/avatar-face";
import { useAuthStore } from "@/stores";

/**
 * The reader's own face in a transcript: their picture, the face generated for
 * them, or - for a signed-out reader of a shared transcript - a plain glyph, since
 * there is no id to draw a face from and one drawn from nothing would be
 * somebody else's. Sized by the circle it is put in.
 */
export function YouFace() {
  const { user, avatarVersion } = useAuthStore();
  if (user?.avatar_url) {
    return (
      <Image
        src={`/api/users/avatar/${user.id}?v=${avatarVersion}`}
        alt=""
        width={36}
        height={36}
        className="h-full w-full object-cover"
        unoptimized
      />
    );
  }
  if (user) return <AvatarFace seed={user.id} colorSlot={user.avatar_color} />;
  return <User className="h-4 w-4" />;
}
