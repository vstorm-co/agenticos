import { ImageResponse } from "next/og";

import { readBranding } from "@/lib/branding-server";

export const size = { width: 180, height: 180 };
export const contentType = "image/png";

/**
 * The home-screen icon when no favicon has been uploaded: one letter, on black.
 *
 * The letter is the deployment's, not this build's - a renamed installation whose
 * touch icon still shows `A` is the rename half-applied. An uploaded favicon does
 * not replace this: iOS reads `apple-touch-icon` and nothing else, and a 32-pixel
 * favicon scaled to 180 is worse than an initial.
 *
 * Not `force-static` for the same reason the OpenGraph image is not.
 */
export default async function AppleIcon() {
  const { appName } = await readBranding();
  const initial = appName.charAt(0).toUpperCase();
  return new ImageResponse(
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "#0E0E0C",
        color: "#C5F94A",
        fontSize: 110,
        fontWeight: 800,
        letterSpacing: "-0.04em",
        fontFamily: "sans-serif",
      }}
    >
      {initial}
    </div>,
    { ...size },
  );
}
