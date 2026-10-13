"use client";

import { useSyncExternalStore, type ReactNode } from "react";
import { useReducedMotion } from "motion/react";
import { isAudioSupported, useMicrophone, VoiceBeam, type VoiceBeamProps } from "voice-glow";

import { useMounted } from "@/hooks/use-mounted";
import { useResolvedTheme } from "@/hooks/use-resolved-theme";
import { useVoiceGlowStore } from "@/stores/voice-glow-store";

export { useMicrophone };

export interface VoiceGlowProps {
  children: ReactNode;
  /** The live microphone stream. Null leaves the glow at its resting breath. */
  stream?: MediaStream | null;
  /** Whether to glow at all. */
  active?: boolean;
  /**
   * The waiting pulse: the same edge, travelling rather than reacting. For the
   * stretch after a person stops talking and before the answer arrives.
   */
  processing?: boolean;
  /** Matches the glow's corners to the element's own. */
  borderRadius?: number;
  className?: string;
}

/**
 * The beam's settings for each style a person can pick.
 *
 * Vivid is the colourful glow the composer first shipped with. Subtle is one
 * neutral edge with no resting breath, no band and no warp, and a slower
 * waiting sweep - the default, because the colourful one read as a light show on
 * a console that is otherwise neutral.
 */
const STYLE_PROPS: Record<"vivid" | "subtle", Partial<VoiceBeamProps>> = {
  vivid: { colorVariant: "colorful", idle: 0.45, glowSize: 1.5 },
  subtle: {
    colorVariant: "mono",
    idle: 0,
    strength: 0.25,
    bandStrength: 0,
    distortion: 0,
    flow: 0,
    glowSize: 1,
    processingDuration: 2.4,
  },
};

/**
 * A glow along the bottom edge that rises with the voice it is hearing.
 *
 * It is fed the stream rather than a level, so the analysis is the library's
 * and no audio ever leaves the page - nothing is connected to the output, and
 * the stream is the one the microphone button already opened.
 *
 * How it looks is the person's preference (`useVoiceGlowStore`): vivid, subtle
 * or off. Under `prefers-reduced-motion` there is no glow at all, whatever the
 * preference says - a glow that cannot move says nothing, so the recording
 * bar's level indicator and its text carry the state instead.
 *
 * Where there is no Web Audio at all the children are returned untouched. The
 * check is read through `useSyncExternalStore` with a server snapshot of
 * `false`, which is what lets the server and the first client render agree: the
 * swap therefore happens once, on hydration, before anybody has typed into what
 * it wraps. The preference and the media query are gated on `useMounted` for
 * the same reason - neither is known on the server.
 *
 * Switching the style or the motion setting never swaps the wrapper: the beam
 * stays mounted and is silenced (paused, no stream, no strength), so the
 * composer inside it keeps its draft, its focus and its caret.
 */
/** Whether a browser can analyse audio never changes within a page's life. */
const subscribeToNothing = () => () => {};

export function VoiceGlow({
  children,
  stream,
  active = true,
  processing = false,
  borderRadius,
  className,
}: VoiceGlowProps) {
  const theme = useResolvedTheme();
  const audio = useSyncExternalStore(subscribeToNothing, isAudioSupported, () => false);
  const style = useVoiceGlowStore((state) => state.style);
  const reduced = useReducedMotion();
  const mounted = useMounted();

  if (!audio) return <>{children}</>;

  const shown = mounted && style !== "off" && !reduced;
  const look = STYLE_PROPS[style === "vivid" ? "vivid" : "subtle"];

  return (
    <VoiceBeam
      {...look}
      stream={shown ? stream : null}
      active={shown && active}
      processing={shown && processing}
      paused={!shown || !active}
      // Silenced rather than unmounted, so what it wraps is never remounted.
      strength={shown ? look.strength : 0}
      theme={theme}
      scale={1.6}
      // Same as `Beam`: the library clips its own wrapper, and the composer
      // opens the slash palette above itself. Inline, to outrank the rule the
      // library injects.
      style={{ overflow: "visible" }}
      borderRadius={borderRadius}
      className={className}
    >
      {children}
    </VoiceBeam>
  );
}
