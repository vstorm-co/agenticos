import { ImageResponse } from "next/og";

import { readBranding } from "@/lib/branding-server";
import { LOGO_DATA_URI } from "@/lib/logo.generated";
import { SITE } from "@/lib/seo";

export const size = { width: 180, height: 180 };
export const contentType = "image/png";

/** The mark's tile, which a renamed deployment's initial sits on too. */
const TILE = "#2b2547";

/**
 * The home-screen icon when no favicon has been uploaded: the AgenticOS mark, or
 * a renamed deployment's initial on the mark's tile.
 *
 * The letter is the deployment's, not this build's - a renamed installation whose
 * touch icon still shows the AgenticOS blob is the rename half-applied. An
 * uploaded favicon does not replace this: iOS reads `apple-touch-icon` and
 * nothing else, and a 32-pixel favicon scaled to 180 is worse than an initial.
 *
 * Not `force-static` for the same reason the OpenGraph image is not.
 */
export default async function AppleIcon() {
  const { appName } = await readBranding();
  if (appName === SITE.name) {
    // The mark's corners are the tile's colour behind it, so iOS's own rounding
    // and a maskable crop both land on violet rather than on a white corner.
    return new ImageResponse(
      <div style={{ width: "100%", height: "100%", display: "flex", background: TILE }}>
        <img src={LOGO_DATA_URI} alt="" width={180} height={180} />
      </div>,
      { ...size },
    );
  }
  const initial = appName.charAt(0).toUpperCase();
  return new ImageResponse(
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: TILE,
        color: "#bbd1ff",
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
