import { ImageResponse } from "next/og";

import { LOGO_DATA_URI } from "@/lib/logo.generated";

/** Dynamic favicon - the AgenticOS mark, which is its own tile. Renders at 32x32. */
export const size = { width: 32, height: 32 };
export const contentType = "image/png";
export const dynamic = "force-static";

export default function Icon() {
  // eslint-disable-next-line @next/next/no-img-element -- ImageResponse renders through Satori; next/image cannot run there, and the src is a data URI.
  return new ImageResponse(<img src={LOGO_DATA_URI} alt="" width={32} height={32} />, { ...size });
}
