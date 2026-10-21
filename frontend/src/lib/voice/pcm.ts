/**
 * A relayed voice call's audio in the browser (#54, slice 1): Gemini Live, xAI
 * and Azure, whose audio passes through our own socket rather than WebRTC.
 * Not verified live - only OpenAI was available to test against.
 *
 * Capture is dictation's (#1797): raw samples from a `ScriptProcessorNode`,
 * mixed to mono, resampled to the model's input rate and sent as 16-bit PCM.
 * Not an `AudioWorklet`: a worklet is a module loaded by URL, and the console's
 * CSP (`script-src` with a nonce and `'strict-dynamic'`, no `worker-src`) admits
 * none - `use-dictation.ts` records why.
 *
 * Playback schedules each chunk back to back at the model's output rate (the
 * browser resamples) into a `MediaStream`, which the call view plays and the
 * level meter reads, like a WebRTC call's remote stream. The played position is
 * counted in the bytes the server sent, at the model's rate: what the server
 * passes to `interrupt(played_bytes=...)` when the caller talks over the agent.
 */

import { createResampler, mixToMono, toPcm16 } from "@/lib/wav-encoder";

/**
 * How often the browser tells the server how much of the agent's audio it has
 * played, while it changes. Barge-in cuts at the last report, so a stale one
 * leaves heard audio counted as unheard; the end of playback is reported at
 * once (`onDrained`), so an answer that finished playing is never taken for
 * one the caller talked over.
 */
export const PLAYED_EVERY_MS = 100;

/** About 85 ms of a 48 kHz context a callback: dictation's buffer. */
const CAPTURE_FRAMES = 4096;
const BYTES_PER_SAMPLE = 2;

export interface PcmCapture {
  stop(): void;
}

/** Capture `stream` as 16-bit mono PCM at `rate`, one chunk a processor callback. */
export function createPcmCapture(
  context: AudioContext,
  stream: MediaStream,
  rate: number,
  onChunk: (pcm: ArrayBuffer) => void,
): PcmCapture {
  const resample = createResampler(context.sampleRate, rate);
  const source = context.createMediaStreamSource(stream);
  const processor = context.createScriptProcessor(CAPTURE_FRAMES, 2, 1);
  // A processor only runs while connected to the destination; the gain at zero
  // keeps the microphone from playing back through the speakers.
  const silent = context.createGain();
  silent.gain.value = 0;
  processor.addEventListener("audioprocess", ({ inputBuffer }) => {
    const channels = Array.from({ length: inputBuffer.numberOfChannels }, (_, i) =>
      inputBuffer.getChannelData(i),
    );
    onChunk(toPcm16(resample(mixToMono(channels))));
  });
  source.connect(processor);
  processor.connect(silent);
  silent.connect(context.destination);
  return {
    stop() {
      for (const node of [source, processor, silent]) node.disconnect();
    },
  };
}

export interface PcmPlayer {
  /** The agent's audio, for the call view's `<audio>` element and the level meter. */
  stream: MediaStream;
  /** Play one chunk of 16-bit little-endian mono PCM after everything queued. */
  enqueue(pcm: ArrayBuffer): void;
  /**
   * Bytes received so far that are behind the playhead - played, or dropped by
   * {@link PcmPlayer.clear}. Only ever grows.
   */
  playedBytes(): number;
  /** Drop everything queued: the caller talked over the agent. */
  clear(): void;
  close(): void;
}

interface Scheduled {
  node: AudioBufferSourceNode;
  start: number;
  end: number;
  bytes: number;
}

/**
 * Play the agent's PCM at `rate`, counting what has been played. `onDrained`
 * runs when the last chunk queued has finished playing.
 */
export function createPcmPlayer(
  context: AudioContext,
  rate: number,
  onDrained: () => void = () => {},
): PcmPlayer {
  const destination = context.createMediaStreamDestination();
  let queued: Scheduled[] = [];
  /** Bytes of chunks already finished or dropped. */
  let passed = 0;
  /** When the next chunk starts: right after the last one queued. */
  let nextStart = 0;

  const stopAll = () => {
    for (const { node } of queued) {
      node.stop();
      node.disconnect();
    }
    passed += queued.reduce((total, { bytes }) => total + bytes, 0);
    queued = [];
    nextStart = 0;
  };

  return {
    stream: destination.stream,
    enqueue(pcm) {
      const samples = Math.floor(pcm.byteLength / BYTES_PER_SAMPLE);
      if (samples === 0) return;
      const buffer = context.createBuffer(1, samples, rate);
      const channel = buffer.getChannelData(0);
      const view = new DataView(pcm);
      for (let i = 0; i < samples; i += 1) {
        channel[i] = view.getInt16(i * BYTES_PER_SAMPLE, true) / 0x8000;
      }
      const node = context.createBufferSource();
      node.buffer = buffer;
      node.connect(destination);
      const start = Math.max(context.currentTime, nextStart);
      node.start(start);
      nextStart = start + samples / rate;
      const scheduled = { node, start, end: nextStart, bytes: samples * BYTES_PER_SAMPLE };
      queued.push(scheduled);
      node.onended = () => {
        // Only the last chunk's end is the queue draining; a cleared one's is not.
        if (queued[queued.length - 1] === scheduled) onDrained();
      };
    },
    playedBytes() {
      const now = context.currentTime;
      while (queued.length > 0 && queued[0]!.end <= now) {
        const done = queued.shift()!;
        done.node.disconnect();
        passed += done.bytes;
      }
      const playing = queued[0];
      if (!playing || now <= playing.start) return passed;
      const fraction = (now - playing.start) / (playing.end - playing.start);
      // Whole samples only: the server maps this onto 16-bit audio.
      const partial = Math.floor((fraction * playing.bytes) / BYTES_PER_SAMPLE) * BYTES_PER_SAMPLE;
      return passed + partial;
    },
    clear: stopAll,
    close() {
      stopAll();
      destination.disconnect();
    },
  };
}
