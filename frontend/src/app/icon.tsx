import { ImageResponse } from "next/og";

import { AMIGO_HEAD_DATA_URI } from "@/lib/amigo-head.generated";

/** Dynamic favicon - Amigo's head on the brand black. Renders at 32x32. */
export const size = { width: 32, height: 32 };
export const contentType = "image/png";
export const dynamic = "force-static";

export default function Icon() {
  return new ImageResponse(
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "#0E0E0C",
        borderRadius: "6px",
      }}
    >
      {/* 32 is twice the drawing's 16, so every pixel lands on two and the edges
            stay hard. The crop carries its own margin, which is the inset. */}
      <img src={AMIGO_HEAD_DATA_URI} alt="" width={32} height={32} />
    </div>,
    { ...size },
  );
}
