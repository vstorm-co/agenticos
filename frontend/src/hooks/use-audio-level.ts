"use client";

import { useEffect, useState } from "react";
import { getAudioContext } from "voice-glow";

/** How often the level is read - the dictation meter's pace. */
export const LEVEL_EVERY_MS = 70;
const GAIN = 7;
const ATTACK = 0.35;
const RELEASE = 0.08;

/**
 * How loud a stream is right now, 0..1 - the caller's microphone or the
 * agent's voice (#54). The call view's visual is driven by this, never by a
 * loop that only looks alive. The constants are the dictation meter's
 * (`use-dictation.ts`): a quick rise and a slower fall.
 */
export function useAudioLevel(stream: MediaStream | null): number {
  // Which stream the reading is of, so a new stream starts from silence
  // without resetting state inside the effect.
  const [reading, setReading] = useState<{ stream: MediaStream | null; level: number }>({
    stream: null,
    level: 0,
  });
  useEffect(() => {
    const context = stream && stream.getAudioTracks().length > 0 ? getAudioContext() : null;
    if (!stream || !context) return;
    const source = context.createMediaStreamSource(stream);
    const analyser = context.createAnalyser();
    analyser.fftSize = 512;
    source.connect(analyser);
    const samples = new Uint8Array(analyser.fftSize);
    let smoothed = 0;
    const timer = window.setInterval(() => {
      analyser.getByteTimeDomainData(samples);
      let sum = 0;
      for (const sample of samples) sum += ((sample - 128) / 128) ** 2;
      const rms = Math.min(1, Math.sqrt(sum / samples.length) * GAIN);
      smoothed += (rms - smoothed) * (rms > smoothed ? ATTACK : RELEASE);
      setReading({ stream, level: smoothed });
    }, LEVEL_EVERY_MS);
    return () => {
      window.clearInterval(timer);
      source.disconnect();
    };
  }, [stream]);
  return stream !== null && reading.stream === stream ? reading.level : 0;
}
