"use client";

import { useSyncExternalStore, type ReactNode } from "react";
import { isAudioSupported, useMicrophone, VoiceBeam } from "voice-glow";

import { useResolvedTheme } from "@/hooks/use-resolved-theme";

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
 * A glow along the bottom edge that rises with the voice it is hearing.
 *
 * It is fed the stream rather than a level, so the analysis is the library's
 * and no audio ever leaves the page - nothing is connected to the output, and
 * the stream is the one the microphone button already opened.
 *
 * Deliberately a sibling of the speech recognition rather than its driver. The
 * Web Speech API captures audio itself and hands back text without exposing a
 * stream, so the two open the microphone separately: this one only watches the
 * level, and stopping it stops no dictation.
 *
 * Where there is no Web Audio at all the children are returned untouched. The
 * check is read through `useSyncExternalStore` with a server snapshot of
 * `false`, which is what lets the server and the first client render agree: the
 * swap therefore happens once, on hydration, before anybody has typed into what
 * it wraps.
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

  if (!audio) return <>{children}</>;

  return (
    <VoiceBeam
      stream={stream}
      active={active}
      processing={processing}
      paused={!active}
      theme={theme}
      colorVariant="colorful"
      scale={1.6}
      // The resting level, raised well off the library's default: at 0 the glow
      // is a hairline nobody notices, and the point of this one is that the
      // composer looks alive before anybody speaks into it.
      idle={0.45}
      glowSize={1.5}
      borderRadius={borderRadius}
      className={className}
    >
      {children}
    </VoiceBeam>
  );
}
