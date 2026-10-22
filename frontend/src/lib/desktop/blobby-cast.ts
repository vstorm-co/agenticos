/**
 * Blobby's cast, and the face any of its characters wears.
 *
 * The cast is `blobby-cast.json`, which the desktop shell also compiles in for
 * its menu (`blobby.rs`): one list, so the menu and this page cannot offer
 * different creatures under one name. Each member is a `blobatar` with its shape
 * and hue pinned, so it is the same creature on every machine.
 */

import cast from "@/lib/desktop/blobby-cast.json";
import { avatarHue } from "@/lib/avatar-color";
import type { BlobbyCharacter } from "@/lib/desktop/commands";

export interface CastMember {
  id: string;
  name: string;
  /** The `shape` trait, 0..1, which picks the silhouette (`blobatar`'s bands). */
  shape: number;
  hue: number;
}

export const BLOBBY_CAST: readonly CastMember[] = cast;

/** What a `<Blobatar>` is drawn from for a character. */
export interface Face {
  seed: string;
  hue: number | undefined;
  traits: { shape: number } | undefined;
}

export function faceOf(character: BlobbyCharacter): Face {
  switch (character.kind) {
    case "cast": {
      // A member a newer shell knows and this console does not draws the first.
      const member = BLOBBY_CAST.find((m) => m.id === character.id) ?? BLOBBY_CAST[0]!;
      return { seed: member.id, hue: member.hue, traits: { shape: member.shape } };
    }
    case "agent":
      // The handle, as `AgentAvatar` draws it: the same face the agent wears everywhere.
      return { seed: character.slug, hue: avatarHue(character.color_slot), traits: undefined };
    case "custom":
      return { seed: character.seed, hue: avatarHue(character.color_slot), traits: undefined };
  }
}

/** Which set of lines a character speaks: its own for the cast, a shared one otherwise. */
export function voiceOf(character: BlobbyCharacter): string {
  if (character.kind === "cast" && BLOBBY_CAST.some((m) => m.id === character.id)) {
    return character.id;
  }
  return "anyone";
}

/** How many lines each voice has in the catalog (`desktop.blobby.lines.<voice>.<n>`). */
export const LINES_PER_VOICE = 4;

/** One line, never the one said last. */
export function pickLine(random: () => number, last: number | null): number {
  const candidates = Array.from({ length: LINES_PER_VOICE }, (_, i) => i).filter((i) => i !== last);
  return candidates[Math.floor(random() * candidates.length)]!;
}
