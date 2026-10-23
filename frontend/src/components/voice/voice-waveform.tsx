"use client";

import { useEffect, useRef } from "react";

import {
  agentShare,
  barTarget,
  easeBar,
  type WaveLevels,
  type WaveVisual,
} from "@/lib/voice/waveform";

const BAR_WIDTH = 3;
const BAR_GAP = 3;
/** A colour token as the canvas can paint it: its declared value. */
function token(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/**
 * The call bar's waveform (#54): mirrored bars, weighted to the centre, drawn
 * from the real levels - the theme's ink for the caller, its muted ink for the
 * agent, the warning colour while an approval waits. No hue of its own: the
 * console is neutral, and colour is for meaning. The props
 * are read through refs by one animation loop, so a level changing many times a
 * second redraws the canvas without re-rendering anything. The layout leaves it
 * out under reduced motion; a stepped meter stands in.
 */
export function VoiceWaveform({
  visual,
  levels,
  compact = false,
}: {
  visual: WaveVisual;
  levels: WaveLevels;
  /** `/chat`'s pill: a short wave in the ink of whatever holds it, both voices alike. */
  compact?: boolean;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const live = useRef({ visual, levels });
  useEffect(() => {
    live.current = { visual, levels };
  });

  useEffect(() => {
    const canvas = canvasRef.current as HTMLCanvasElement;
    const context = canvas.getContext("2d");
    if (context === null) return;
    let bars: number[] = [];
    let noise: number[] = [];
    let agentMix = 0;
    let warnMix = 0;
    // The colours, read once and again when the theme changes - not every frame.
    const read = () => {
      if (compact) {
        const own = getComputedStyle(canvas).color;
        return { ink: own, agentInk: own, warning: token("--color-warning") };
      }
      return {
        ink: token("--color-foreground"),
        agentInk: token("--color-muted-foreground"),
        warning: token("--color-warning"),
      };
    };
    let { ink, agentInk, warning } = read();
    const theme = new MutationObserver(() => {
      ({ ink, agentInk, warning } = read());
    });
    theme.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class", "style"],
    });
    let frame = requestAnimationFrame(function draw(t: number) {
      frame = requestAnimationFrame(draw);
      const width = canvas.clientWidth;
      const height = canvas.clientHeight;
      if (width === 0 || height === 0) return;
      const ratio = Math.min(2, window.devicePixelRatio);
      if (canvas.width !== Math.round(width * ratio)) canvas.width = Math.round(width * ratio);
      if (canvas.height !== Math.round(height * ratio)) canvas.height = Math.round(height * ratio);
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      context.clearRect(0, 0, width, height);

      const { visual: shown, levels: now } = live.current;
      const count = Math.max(12, Math.floor((width + BAR_GAP) / (BAR_WIDTH + BAR_GAP)));
      if (bars.length !== count) {
        bars = Array<number>(count).fill(0.04);
        noise = Array<number>(count).fill(0.5);
      }
      // Eased over a few hundred ms, so a hand-over between speakers reads as one motion.
      agentMix += (agentShare(shown, now) - agentMix) * 0.08;
      warnMix += ((shown === "approval" ? 1 : 0) - warnMix) * 0.06;
      const left = (width - (count * (BAR_WIDTH + BAR_GAP) - BAR_GAP)) / 2;
      const alpha = shown === "quiet" ? 0.3 : 0.85;

      for (let index = 0; index < count; index++) {
        noise[index] = (noise[index] as number) + (Math.random() - (noise[index] as number)) * 0.18;
        const target = barTarget(shown, index, count, t, now, noise[index] as number);
        bars[index] = easeBar(bars[index] as number, target);
        const barHeight = Math.max(3, (bars[index] as number) * height);
        const x = left + index * (BAR_WIDTH + BAR_GAP);
        const y = (height - barHeight) / 2;
        // Three layers crossfaded: the caller's ink, the agent's muted ink, the warning.
        const layers: [string, number][] = [
          [ink, (1 - agentMix) * (1 - warnMix)],
          [agentInk, agentMix * (1 - warnMix)],
          [warning, warnMix],
        ];
        for (const [fill, share] of layers) {
          if (share < 0.01) continue;
          context.globalAlpha = alpha * share;
          context.fillStyle = fill;
          context.beginPath();
          context.roundRect(x, y, BAR_WIDTH, barHeight, 1.5);
          context.fill();
        }
      }
      context.globalAlpha = 1;
    });
    return () => {
      cancelAnimationFrame(frame);
      theme.disconnect();
    };
  }, [compact]);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      className={compact ? "block h-6 w-full" : "block h-10 w-full sm:h-11"}
    />
  );
}
