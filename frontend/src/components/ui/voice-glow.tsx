"use client";

import { useEffect, useRef, useSyncExternalStore, type ReactNode } from "react";
import { getAudioContext, isAudioSupported, useMicrophone } from "voice-glow";

import { useMounted } from "@/hooks/use-mounted";
import { useReducedMotion } from "@/hooks/use-reduced-motion";
import { cn } from "@/lib/utils";
import { useVoiceGlowStore } from "@/stores/voice-glow-store";

export { useMicrophone };

export interface VoiceGlowProps {
  children: ReactNode;
  /** The live microphone stream. Null leaves the glow at rest. */
  stream?: MediaStream | null;
  /** Whether to glow at all. */
  active?: boolean;
  /**
   * The waiting sweep: the glow travelling rather than reacting, for the stretch
   * after a person stops talking and before the text arrives.
   */
  processing?: boolean;
  className?: string;
}

/** RMS of a speaking voice sits near 0.05-0.15; this puts that near the top. */
const LEVEL_GAIN = 7;
/** How fast the glow follows a rise and lets go of a fall, per frame. */
const ATTACK = 0.35;
const RELEASE = 0.08;

/**
 * A soft bloom beneath the composer that rises with the voice it is hearing.
 *
 * It sits *behind and below* the box rather than inside it: the box holds the
 * text being dictated, and colour washing over that text read as a stain, not
 * as listening. Its look is the person's Voice glow preference - `subtle` is
 * the console's own ink (dark on the light theme, light on the dark one, from
 * `--foreground`), `vivid` a violet-to-cyan gradient - and `off`, an unmounted
 * page, or reduced motion draw nothing at all, because a glow that cannot move
 * says nothing.
 *
 * The level is read from the stream it is given, through the page's shared
 * AudioContext, and written to a CSS variable once a frame - never to state, so
 * the composer it wraps is not re-rendered sixty times a second. Nothing is
 * connected to the output: the audio is analysed and never played back.
 *
 * The wrapper element is the same in every state, so switching the preference
 * never remounts the composer inside it (its draft, focus and caret survive).
 */
const subscribeToNothing = () => () => {};

export function VoiceGlow({
  children,
  stream,
  active = true,
  processing = false,
  className,
}: VoiceGlowProps) {
  const audio = useSyncExternalStore(subscribeToNothing, isAudioSupported, () => false);
  const style = useVoiceGlowStore((state) => state.style);
  const reduced = useReducedMotion();
  const mounted = useMounted();
  const glowRef = useRef<HTMLDivElement>(null);

  const shown = audio && mounted && style !== "off" && !reduced;
  const listening = shown && active && !processing && stream != null;

  useEffect(() => {
    const glow = glowRef.current;
    const context = listening ? getAudioContext() : null;
    if (!glow || !stream || !context) return;
    const source = context.createMediaStreamSource(stream);
    const analyser = context.createAnalyser();
    analyser.fftSize = 1024;
    source.connect(analyser);
    const samples = new Float32Array(analyser.fftSize);
    let level = 0;
    let frame = requestAnimationFrame(function tick() {
      analyser.getFloatTimeDomainData(samples);
      let sum = 0;
      for (const sample of samples) sum += sample * sample;
      const raw = Math.min(1, Math.sqrt(sum / samples.length) * LEVEL_GAIN);
      level += (raw - level) * (raw > level ? ATTACK : RELEASE);
      glow.style.setProperty("--voice-level", level.toFixed(3));
      frame = requestAnimationFrame(tick);
    });
    return () => {
      cancelAnimationFrame(frame);
      source.disconnect();
      analyser.disconnect();
      glow.style.removeProperty("--voice-level");
    };
  }, [listening, stream]);

  return (
    <div className={cn("relative isolate", className)}>
      {shown && (active || processing) ? (
        <div
          ref={glowRef}
          aria-hidden
          data-testid="voice-glow"
          data-style={style}
          data-processing={processing ? "true" : "false"}
          className="voice-glow pointer-events-none absolute -z-10"
        />
      ) : null}
      {children}
    </div>
  );
}
