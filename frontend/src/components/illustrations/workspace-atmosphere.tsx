"use client";

import { useId } from "react";
import { cn } from "@/lib/utils";
import styles from "./workspace-atmosphere.module.css";

export type AtmosphereScene = "landscape" | "orbit" | "contours";

/** Decorative halftone landscape: a quiet visual language for open workspaces. */
export function WorkspaceAtmosphere({
  className,
  animated = false,
  scene = "landscape",
}: {
  className?: string;
  animated?: boolean;
  scene?: AtmosphereScene;
}) {
  const id = useId();
  return (
    <svg
      aria-hidden
      focusable="false"
      className={cn(styles.artwork, animated && styles.animated, "pointer-events-none", className)}
      viewBox="0 0 720 160"
      fill="none"
      preserveAspectRatio="xMidYMid meet"
    >
      <defs>
        <pattern id={`${id}-dots`} width="5" height="5" patternUnits="userSpaceOnUse">
          <circle cx="1.2" cy="1.2" r="0.95" fill="currentColor" />
        </pattern>
        <linearGradient
          id={`${id}-fade`}
          x1="35"
          y1="90"
          x2="690"
          y2="90"
          gradientUnits="userSpaceOnUse"
        >
          <stop stopColor="white" stopOpacity="0" />
          <stop offset="0.25" stopColor="white" stopOpacity="0.85" />
          <stop offset="0.56" stopColor="white" />
          <stop offset="1" stopColor="white" stopOpacity="0" />
        </linearGradient>
        <mask id={`${id}-mask`}>
          <rect width="720" height="160" fill={`url(#${id}-fade)`} />
        </mask>
      </defs>
      <g mask={`url(#${id}-mask)`}>
        {scene === "landscape" ? (
          <>
            {" "}
            <path
              className={styles.landscape}
              d="M0 105C80 134 141 15 233 33C318 49 306 134 399 104C478 78 480 12 571 28C633 39 658 76 720 53V160H0Z"
              fill={`url(#${id}-dots)`}
            />
            <path
              d="M-20 128C87 152 117 71 206 75C302 80 328 167 423 119C518 70 558 80 739 119"
              stroke="currentColor"
              strokeWidth="0.8"
              opacity="0.65"
            />
            <path
              d="M-20 135C87 159 117 78 206 82C302 87 328 174 423 126C518 77 558 87 739 126"
              stroke="currentColor"
              strokeWidth="0.8"
              opacity="0.4"
            />
            <path
              d="M-20 142C87 166 117 85 206 89C302 94 328 181 423 133C518 84 558 94 739 133"
              stroke="currentColor"
              strokeWidth="0.8"
              opacity="0.25"
            />
            <path
              d="M125 35C218 -24 291 77 366 43C450 5 495 3 608 37"
              stroke="currentColor"
              strokeWidth="0.75"
              opacity="0.4"
            />
            <g className={styles.document}>
              <g transform="translate(270 24) rotate(-12)">
                <rect x="-7" y="-7" width="72" height="52" rx="9" fill="var(--color-background)" />
                <rect width="58" height="38" rx="6" stroke="currentColor" strokeWidth="1.2" />
                <path
                  d="M10 12H37M10 19H47M10 26H29"
                  stroke="currentColor"
                  strokeLinecap="round"
                  opacity="0.65"
                />
              </g>
            </g>
            <g className={styles.chart}>
              <g transform="translate(520 52) rotate(9)">
                <rect x="-7" y="-7" width="78" height="62" rx="10" fill="var(--color-background)" />
                <rect width="64" height="48" rx="7" stroke="currentColor" strokeWidth="1.2" />
                <path
                  d="M11 34L24 23L34 28L52 13"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
                <circle cx="52" cy="13" r="2.5" fill="currentColor" />
              </g>
            </g>
            <circle cx="417" cy="24" r="3" fill="currentColor" opacity="0.7" />
            <path d="M180 17V27M175 22H185" stroke="currentColor" strokeLinecap="round" />
          </>
        ) : scene === "orbit" ? (
          <>
            <g className={styles.landscape}>
              <ellipse
                cx="365"
                cy="94"
                rx="225"
                ry="45"
                transform="rotate(-12 365 94)"
                fill={`url(#${id}-dots)`}
              />
              <ellipse
                cx="365"
                cy="94"
                rx="180"
                ry="58"
                transform="rotate(12 365 94)"
                stroke="currentColor"
                opacity="0.55"
              />
              <ellipse
                cx="365"
                cy="94"
                rx="265"
                ry="28"
                transform="rotate(-12 365 94)"
                stroke="currentColor"
                opacity="0.35"
              />
            </g>
            <g className={styles.document}>
              <g transform="translate(304 34) rotate(-7 58 43)">
                <rect
                  width="116"
                  height="86"
                  rx="10"
                  fill="var(--color-background)"
                  stroke="currentColor"
                />
                <path d="M0 23H116M14 13H36" stroke="currentColor" opacity="0.5" />
                <circle cx="18" cy="48" r="6" fill={`url(#${id}-dots)`} stroke="currentColor" />
                <path
                  d="M34 45H91M34 53H72M14 68H100"
                  stroke="currentColor"
                  strokeLinecap="round"
                  opacity="0.6"
                />
              </g>
            </g>
            <g className={styles.chart}>
              <circle
                cx="188"
                cy="93"
                r="13"
                fill="var(--color-background)"
                stroke="currentColor"
              />
              <path d="M183 93H193M188 88V98" stroke="currentColor" />
              <rect
                x="509"
                y="37"
                width="29"
                height="29"
                rx="8"
                transform="rotate(12 523 51)"
                fill="var(--color-background)"
                stroke="currentColor"
              />
              <path d="M516 52L522 57L532 46" stroke="currentColor" />
              <circle cx="522" cy="117" r="4" fill="currentColor" />
              <circle cx="260" cy="38" r="2" fill="currentColor" />
            </g>
          </>
        ) : (
          <>
            <g className={styles.landscape}>
              {Array.from({ length: 10 }, (_, i) => (
                <ellipse
                  key={i}
                  cx="365"
                  cy="84"
                  rx={62 + i * 20}
                  ry={14 + i * 5}
                  transform="rotate(-14 365 84)"
                  stroke="currentColor"
                  strokeWidth={i % 3 === 0 ? 1.1 : 0.65}
                  opacity={0.2 + i * 0.065}
                />
              ))}
              <path
                d="M122 119C204 135 247 61 327 72S454 134 590 73L622 144H107Z"
                fill={`url(#${id}-dots)`}
                opacity="0.65"
              />
            </g>
            <g className={styles.document}>
              <path d="M253 94L357 49L482 91" stroke="currentColor" strokeDasharray="2 5" />
              <circle
                cx="253"
                cy="94"
                r="15"
                fill="var(--color-background)"
                stroke="currentColor"
              />
              <circle cx="253" cy="94" r="5" fill={`url(#${id}-dots)`} stroke="currentColor" />
              <rect
                x="337"
                y="29"
                width="40"
                height="40"
                rx="11"
                fill="var(--color-background)"
                stroke="currentColor"
              />
              <path d="M348 49H366M357 40V58" stroke="currentColor" />
            </g>
            <g className={styles.chart}>
              <circle
                cx="482"
                cy="91"
                r="19"
                fill="var(--color-background)"
                stroke="currentColor"
              />
              <path
                d="M475 91L480 96L490 85"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
              />
              <circle cx="406" cy="126" r="3" fill="currentColor" />
            </g>
          </>
        )}
      </g>
    </svg>
  );
}
