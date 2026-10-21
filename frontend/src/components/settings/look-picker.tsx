"use client";

import { useTranslations } from "next-intl";
import { useRef, type CSSProperties, type KeyboardEvent } from "react";

import { LOOKS, type Look } from "@/lib/appearance";
import { cn } from "@/lib/utils";

/**
 * What each look's thumbnail is painted in: the column, the page and a line of
 * ink, light and dark.
 *
 * An illustration of `looks.css`, not its tokens: the tokens live on `:root`,
 * where a thumbnail of another look cannot reach them, so a picture of the
 * standard look drawn while Midnight is on would otherwise be Midnight.
 */
const PREVIEW: Record<Look, { light: [string, string, string]; dark: [string, string, string] }> = {
  standard: {
    light: ["oklch(96.3% 0.002 265)", "oklch(97.8% 0.002 265)", "oklch(17.5% 0.004 265)"],
    dark: ["oklch(20.5% 0.0025 265)", "oklch(23.5% 0.0025 265)", "oklch(94.5% 0.003 265)"],
  },
  glass: {
    light: [
      "oklch(97% 0.004 265 / 0.45)",
      "oklch(98.5% 0.002 265 / 0.62)",
      "oklch(17.5% 0.004 265)",
    ],
    dark: ["oklch(22% 0.004 265 / 0.4)", "oklch(21% 0.004 265 / 0.62)", "oklch(94.5% 0.003 265)"],
  },
  graphite: {
    light: ["oklch(95.2% 0.004 75)", "oklch(97.2% 0.003 75)", "oklch(20% 0.008 75)"],
    dark: ["oklch(19.5% 0.004 75)", "oklch(22.5% 0.004 75)", "oklch(94% 0.005 75)"],
  },
  midnight: {
    light: ["oklch(95% 0.012 255)", "oklch(97.3% 0.008 255)", "oklch(20% 0.03 265)"],
    dark: ["oklch(14% 0.02 268)", "oklch(16.5% 0.022 268)", "oklch(95% 0.01 268)"],
  },
  paper: {
    light: ["oklch(94.5% 0.014 85)", "oklch(97% 0.012 85)", "oklch(25% 0.02 60)"],
    dark: ["oklch(20% 0.012 70)", "oklch(23% 0.013 70)", "oklch(93% 0.02 85)"],
  },
};

/** The soft backdrop a glass thumbnail sits on, as the glass console does in a browser. */
const GLASS_BACKDROP =
  "radial-gradient(circle at 15% 10%, oklch(78% 0.1 277 / 0.8), transparent 60%), radial-gradient(circle at 90% 30%, oklch(82% 0.08 200 / 0.8), transparent 60%), radial-gradient(circle at 60% 100%, oklch(84% 0.08 320 / 0.8), transparent 60%)";

function Thumbnail({ look, dark }: { look: Look; dark: boolean }) {
  const [column, page, ink] = PREVIEW[look][dark ? "dark" : "light"];
  const backdrop: CSSProperties = look === "glass" ? { backgroundImage: GLASS_BACKDROP } : {};
  return (
    <span
      aria-hidden
      className="border-border flex h-16 w-full overflow-hidden rounded-md border"
      style={backdrop}
    >
      <span className="flex w-1/3 flex-col gap-1 p-1.5" style={{ background: column }}>
        <span className="h-1 w-3/4 rounded-full opacity-60" style={{ background: ink }} />
        <span className="h-1 w-1/2 rounded-full opacity-40" style={{ background: ink }} />
        <span className="h-1 w-2/3 rounded-full opacity-40" style={{ background: ink }} />
      </span>
      <span className="flex flex-1 flex-col gap-1.5 p-2" style={{ background: page }}>
        <span className="h-1.5 w-1/2 rounded-full opacity-80" style={{ background: ink }} />
        <span className="h-1 w-5/6 rounded-full opacity-30" style={{ background: ink }} />
        <span className="h-1 w-2/3 rounded-full opacity-30" style={{ background: ink }} />
      </span>
    </span>
  );
}

const NEXT_KEYS = new Set(["ArrowRight", "ArrowDown"]);
const PREVIOUS_KEYS = new Set(["ArrowLeft", "ArrowUp"]);

interface LookPickerProps {
  labelledBy: string;
  /** `undefined` before the stored look is known, which checks nothing. */
  value: Look | undefined;
  /** Whether the thumbnails are drawn dark, following the resolved theme. */
  dark: boolean;
  onChange: (look: Look) => void;
}

/**
 * The console's style, as a row of thumbnails: a radio group like
 * `ChoiceGroup`, by role and by keyboard, because a look is chosen by how it
 * looks and a word cannot show that.
 */
export function LookPicker({ labelledBy, value, dark, onChange }: LookPickerProps) {
  const t = useTranslations("appearance.looks");
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  const focusable = Math.max(0, LOOKS.indexOf(value ?? "standard"));

  const onKeyDown = (event: KeyboardEvent, index: number) => {
    const step = NEXT_KEYS.has(event.key) ? 1 : PREVIOUS_KEYS.has(event.key) ? -1 : 0;
    if (step === 0) return;
    event.preventDefault();
    const next = (index + step + LOOKS.length) % LOOKS.length;
    onChange(LOOKS[next]!);
    buttons.current[next]?.focus();
  };

  return (
    <div
      role="radiogroup"
      aria-labelledby={labelledBy}
      className="grid grid-cols-[repeat(auto-fill,minmax(7.5rem,1fr))] gap-2"
    >
      {LOOKS.map((look, index) => {
        const checked = look === value;
        return (
          <button
            key={look}
            ref={(node) => {
              buttons.current[index] = node;
            }}
            type="button"
            role="radio"
            aria-checked={checked}
            tabIndex={index === focusable ? 0 : -1}
            onClick={() => onChange(look)}
            onKeyDown={(event) => onKeyDown(event, index)}
            className={cn(
              "focus-visible:ring-ring flex flex-col gap-1.5 rounded-lg border p-1.5 text-left transition-colors outline-none focus-visible:ring-2",
              checked ? "border-foreground bg-accent" : "hover:bg-accent/60 border-transparent",
            )}
          >
            <Thumbnail look={look} dark={dark} />
            <span className="px-0.5">
              <span className="text-foreground block text-sm font-medium">{t(`${look}.name`)}</span>
              <span className="text-muted-foreground block text-xs">{t(`${look}.hint`)}</span>
            </span>
          </button>
        );
      })}
    </div>
  );
}
