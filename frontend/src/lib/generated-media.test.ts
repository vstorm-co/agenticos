import { describe, expect, it } from "vitest";

import { generatedMediaUrl, SESSION_SURFACE, type MediaSurface } from "./generated-media";

const HOSTED: MediaSurface = { kind: "hosted", publicKey: "pk_abc" };
const TOKEN = `1792689903.${"a".repeat(64)}`;

/**
 * Where a generated file's card fetches it from, on each surface (#2309).
 *
 * The console keeps the address it always had; a hosted page reads through its own
 * key with the link the socket signed, because a visitor has no session to forward.
 */
describe("the address of a generated file", () => {
  it("is the console's own in a signed-in chat", () => {
    expect(generatedMediaUrl({ filename: "abc_image.png" }, SESSION_SURFACE)).toBe(
      "/api/generated/abc_image.png",
    );
  });

  it("ignores a token in a signed-in chat, where the session is what opens it", () => {
    expect(generatedMediaUrl({ filename: "abc_image.png", token: TOKEN }, SESSION_SURFACE)).toBe(
      "/api/generated/abc_image.png",
    );
  });

  it("goes through the page's key with its link on a hosted page", () => {
    expect(generatedMediaUrl({ filename: "abc_video.mp4", token: TOKEN }, HOSTED)).toBe(
      `/api/embed/pk_abc/generated/abc_video.mp4?token=${TOKEN}`,
    );
  });

  it("encodes what it puts in the address", () => {
    const surface: MediaSurface = { kind: "hosted", publicKey: "a/b" };

    expect(generatedMediaUrl({ filename: "x y.png", token: "t&u" }, surface)).toBe(
      "/api/embed/a%2Fb/generated/x%20y.png?token=t%26u",
    );
  });

  it("has none on a hosted page for a result the socket did not sign", () => {
    expect(generatedMediaUrl({ filename: "abc_image.png" }, HOSTED)).toBeNull();
    expect(generatedMediaUrl({ filename: "abc_image.png", token: 7 }, HOSTED)).toBeNull();
  });

  it.each([SESSION_SURFACE, HOSTED])("has none for a file that was not stored", (surface) => {
    expect(generatedMediaUrl({ filename: null, token: TOKEN }, surface)).toBeNull();
    expect(generatedMediaUrl({}, surface)).toBeNull();
  });
});
