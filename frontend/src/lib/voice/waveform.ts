import type { VoiceViewState } from "./call-reducer";

/**
 * What the call bar's waveform shows (#54): a level - the caller's or the
 * agent's - or, where there is no level to show, a working look that says what
 * the call is waiting on. `quiet` is a closed microphone or a call waiting on
 * something other than a voice.
 */
export type WaveVisual =
  | "connecting"
  | "listening"
  | "user"
  | "agent"
  | "interrupted"
  | "thinking"
  | "tool"
  | "approval"
  | "quiet";

const VISUALS: Record<VoiceViewState, WaveVisual> = {
  connecting: "connecting",
  reconnecting: "connecting",
  listening: "listening",
  limitwarn: "listening",
  user: "user",
  agent: "agent",
  interrupted: "interrupted",
  thinking: "thinking",
  tool: "tool",
  approval: "approval",
  noapproval: "quiet",
  limitend: "quiet",
  ended: "quiet",
  dropped: "quiet",
  micblocked: "quiet",
  connfailed: "quiet",
};

/**
 * The visual for a view state. A microphone that is closed - muted, or push to
 * talk with nothing held - draws as quiet while the call listens, so a dead
 * microphone looks dead.
 */
export function waveVisual(view: VoiceViewState, micOpen: boolean): WaveVisual {
  const visual = VISUALS[view];
  return visual === "listening" && !micOpen ? "quiet" : visual;
}

/** The two levels a call has, each 0..1: the caller's microphone and the agent's voice. */
export interface WaveLevels {
  input: number;
  output: number;
}

/**
 * One bar's target height, 0..1, at bar `index` of `count`, `t` ms into the
 * animation, with `noise` (0..1) the bar's own jitter. The bars are weighted to
 * the centre; the working looks travel along them, the levels raise them.
 */
export function barTarget(
  visual: WaveVisual,
  index: number,
  count: number,
  t: number,
  levels: WaveLevels,
  noise: number,
): number {
  const x = count > 1 ? index / (count - 1) : 0.5;
  const centre = Math.abs(x - 0.5) * 2;
  const profile = 1 - centre * centre * 0.78;
  switch (visual) {
    case "user":
      return 0.06 + levels.input * profile * (0.45 + 0.55 * noise);
    case "agent":
      return (
        0.06 +
        levels.output *
          profile *
          (0.6 + 0.4 * Math.sin(index * 0.55 + t * 0.006)) *
          (0.8 + 0.2 * noise)
      );
    case "interrupted":
      return 0.05 + Math.max(levels.output, levels.input) * profile * (0.5 + 0.5 * noise);
    case "listening":
      return 0.05 + levels.input * 1.6 * profile * noise;
    case "thinking": {
      const at = 0.5 + 0.42 * Math.sin(t * 0.0016);
      return 0.05 + 0.34 * Math.exp(-((x - at) ** 2) / 0.006);
    }
    case "tool": {
      const at = ((t * 0.00045) % 1.3) - 0.15;
      return 0.05 + 0.42 * Math.exp(-((x - at) ** 2) / 0.0025) + (index % 6 === 0 ? 0.04 : 0);
    }
    case "connecting":
      return centre < 0.12 ? 0.08 + 0.3 * Math.max(0, Math.sin(t * 0.008 - index * 0.9)) : 0.03;
    case "approval":
      return 0.05 + (0.05 * (Math.sin(t * 0.003 - index * 0.12) + 1)) / 2;
    case "quiet":
      return 0.035;
  }
}

/** A bar eased toward its target: up quickly, down slowly, as a voice decays. */
export function easeBar(current: number, target: number): number {
  return current + (target - current) * (target > current ? 0.4 : 0.14);
}

/** How much of the agent's colour the bars carry: all of it while the agent speaks. */
export function agentShare(visual: WaveVisual, levels: WaveLevels): number {
  if (visual === "agent") return 1;
  // Talked over: the agent's colour while its voice still outweighs the caller's.
  return visual === "interrupted" && levels.output > 0.05 && levels.input < 0.1 ? 1 : 0;
}
