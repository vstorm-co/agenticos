import type { CSSProperties, ReactNode } from "react";
import { cn } from "@/lib/utils";

export interface FormAppearance {
  accent?: string | null;
  width?: "standard" | "wide";
  layout?: "card" | "plain";
}

/** Shared by the public page, authenticated draft test and appearance preview. */
export function FormSurface({
  appearance,
  children,
  preview = false,
}: {
  appearance?: FormAppearance;
  children: ReactNode;
  preview?: boolean;
}) {
  const accent = appearance?.accent;
  const style: CSSProperties | undefined =
    accent && /^#[0-9a-fA-F]{6}$/.test(accent) ? { borderTopColor: accent } : undefined;
  return (
    <div
      className={cn(
        "mx-auto w-full",
        appearance?.width === "wide" ? "max-w-3xl" : "max-w-xl",
        appearance?.layout !== "plain" && "bg-card rounded-2xl border shadow-sm",
        preview ? "p-5" : "p-6 sm:p-10",
        accent && "border-t-4",
      )}
      style={style}
    >
      {children}
    </div>
  );
}

/** Choose a readable button label against an arbitrary validated accent. */
export function formButtonStyle(accent: string | null | undefined): CSSProperties | undefined {
  if (!accent || !/^#[0-9a-fA-F]{6}$/.test(accent)) return undefined;
  const linear = [1, 3, 5].map((offset) => {
    const value = parseInt(accent.slice(offset, offset + 2), 16) / 255;
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
  const luminance = 0.2126 * linear[0]! + 0.7152 * linear[1]! + 0.0722 * linear[2]!;
  return { backgroundColor: accent, color: luminance > 0.179 ? "#000000" : "#ffffff" };
}
