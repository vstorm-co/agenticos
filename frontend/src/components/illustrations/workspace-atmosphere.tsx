"use client";

import { useId } from "react";
import { cn } from "@/lib/utils";

/** Decorative halftone landscape: a quiet visual language for open workspaces. */
export function WorkspaceAtmosphere({ className }: { className?: string }) {
  const id = useId();
  return (
    <svg
      aria-hidden
      focusable="false"
      className={cn("text-foreground/30 pointer-events-none", className)}
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
          <stop offset="0.25" stopColor="white" stopOpacity="0.6" />
          <stop offset="0.56" stopColor="white" />
          <stop offset="1" stopColor="white" stopOpacity="0" />
        </linearGradient>
        <mask id={`${id}-mask`}>
          <rect width="720" height="160" fill={`url(#${id}-fade)`} />
        </mask>
      </defs>
      <g mask={`url(#${id}-mask)`}>
        <path
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
        <circle cx="417" cy="24" r="3" fill="currentColor" opacity="0.7" />
        <path d="M180 17V27M175 22H185" stroke="currentColor" strokeLinecap="round" />
      </g>
    </svg>
  );
}
