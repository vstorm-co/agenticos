"use client";

import { useMemo } from "react";
import { encode } from "uqr";

/**
 * A QR code, drawn as one SVG path of dark modules on a light ground with the
 * quiet zone the standard asks for. Light whatever the theme: a scanner reads
 * dark on light, and an inverted code is one some phones refuse.
 */
export function QrCode({
  value,
  label,
  size = 208,
}: {
  value: string;
  label: string;
  size?: number;
}) {
  const { path, extent } = useMemo(() => {
    const { data, size: modules } = encode(value, { border: 2 });
    let d = "";
    data.forEach((row, y) =>
      row.forEach((dark, x) => {
        if (dark) d += `M${x} ${y}h1v1h-1z`;
      }),
    );
    return { path: d, extent: modules };
  }, [value]);
  return (
    <svg
      role="img"
      aria-label={label}
      viewBox={`0 0 ${extent} ${extent}`}
      width={size}
      height={size}
      shapeRendering="crispEdges"
      className="rounded-lg bg-white"
    >
      <path d={path} fill="#111" />
    </svg>
  );
}
