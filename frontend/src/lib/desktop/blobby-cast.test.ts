import { AVATAR_TRAITS } from "@/lib/avatar-policy";
import { describe, expect, it } from "vitest";

import { avatarHue } from "@/lib/avatar-color";

import { BLOBBY_CAST, faceOf, LINES_PER_VOICE, pickLine, voiceOf } from "./blobby-cast";

describe("the cast", () => {
  it("is six distinct creatures, each a shape and a hue", () => {
    expect(new Set(BLOBBY_CAST.map((m) => m.id)).size).toBe(BLOBBY_CAST.length);
    expect(BLOBBY_CAST.length).toBeGreaterThanOrEqual(6);
    for (const member of BLOBBY_CAST) {
      expect(member.shape).toBeGreaterThanOrEqual(0);
      expect(member.shape).toBeLessThan(1);
    }
  });
});

describe("faceOf", () => {
  it("pins a cast member's shape and hue", () => {
    const [first, second] = BLOBBY_CAST;
    expect(faceOf({ kind: "cast", id: second!.id })).toEqual({
      seed: second!.id,
      hue: second!.hue,
      traits: { shape: second!.shape },
    });
    expect(faceOf({ kind: "cast", id: "from-a-newer-shell" }).seed).toBe(first!.id);
  });

  it("draws an agent from its handle in its colour, as AgentAvatar does", () => {
    expect(
      faceOf({ kind: "agent", agent_id: "a1", slug: "support", name: "Support", color_slot: 3 }),
    ).toEqual({ seed: "support", hue: avatarHue(3), traits: AVATAR_TRAITS });
  });

  it("draws a face of your own from its name", () => {
    expect(faceOf({ kind: "custom", seed: "kacper", color_slot: null })).toEqual({
      seed: "kacper",
      hue: undefined,
      traits: AVATAR_TRAITS,
    });
  });
});

describe("voiceOf and pickLine", () => {
  it("gives the cast their own lines and everyone else a shared set", () => {
    expect(voiceOf({ kind: "cast", id: "mochi" })).toBe("mochi");
    expect(voiceOf({ kind: "cast", id: "nobody" })).toBe("anyone");
    expect(voiceOf({ kind: "custom", seed: "x", color_slot: null })).toBe("anyone");
  });

  it("never says the line it said last", () => {
    for (let last = 0; last < LINES_PER_VOICE; last++) {
      for (const roll of [0, 0.5, 0.99]) {
        expect(pickLine(() => roll, last)).not.toBe(last);
      }
    }
    expect(pickLine(() => 0, null)).toBe(0);
  });
});
