"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getAudioContext, type UseMicrophoneResult } from "voice-glow";

import {
  dictate,
  dictationReason,
  retryAfterSeconds,
  type DictationReason,
} from "@/lib/dictation-api";
import { createResampler, mixToMono, toPcm16, wavBlob } from "@/lib/wav-encoder";

/** Below this smoothed level the room counts as quiet. Speech sits well above it. */
const SILENCE_LEVEL = 0.06;
/** How long quiet lasts before the strip asks whether the microphone is muted. */
const SILENCE_MS = 5000;
/** A recording shorter than this is a slip of the finger, and is not uploaded. */
const MIN_SECONDS = 1;
/** The countdown appears when this many seconds are left before the auto-stop. */
const WARN_SECONDS = 30;
/**
 * What `MediaRecorder` is asked for, in order. The server accepts these three
 * base types; Chromium and Firefox record the first, Safari the last.
 */
const TYPES = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/mp4"];
/** Plenty for speech, and keeps the longest recording near 10 MB. */
const BITS_PER_SECOND = 128_000;
/** How often the recorder hands over a chunk, so a stop loses at most this much. */
const TIMESLICE_MS = 250;
/** RMS of speech is small; this brings a normal voice near the top of 0..1. */
const LEVEL_GAIN = 7;
/** Smoothing: the level rises quickly and falls slowly, so it reads as a meter. */
const ATTACK = 0.35;
const RELEASE = 0.08;
/** The level reaches React at most this often - it is sampled on every frame. */
const LEVEL_EVERY_MS = 70;
/**
 * Providers that are sent a WAV file instead of what `MediaRecorder` makes.
 * Mistral documents WAV and MP3 input, never WebM or Opus.
 */
const WAV_PROVIDERS: ReadonlySet<string> = new Set(["mistral"]);
/** Samples per Web Audio callback: about 85 ms at 48 kHz, the most a stop loses. */
const WAV_BUFFER_SIZE = 4096;
/** These failures keep the recording, because sending it again can succeed. */
const RETRYABLE: ReadonlySet<DictationReason> = new Set([
  "provider_error",
  "timeout",
  "rate_limited",
  "offline",
]);

export type DictationPhase =
  "idle" | "requesting" | "recording" | "transcribing" | "failed" | "too_short";

export interface DictationState {
  phase: DictationPhase;
  /** Whole seconds recorded so far. */
  elapsed: number;
  /** Seconds left before auto-stop, or null when more than 30 remain. */
  remaining: number | null;
  /** True after 5 s below the silence threshold while recording. */
  silent: boolean;
  /** Smoothed input level, 0..1, for the waveform and the 5-step indicator. */
  level: number;
  reason: DictationReason | MicFailure | null;
  /** True when a failed recording is held for Retry. */
  canRetry: boolean;
  /** Seconds after which a rate-limited retry is allowed, else null. */
  retryAfter: number | null;
  /**
   * The latest transcript, with an id that changes on every success. `ChatInput`
   * inserts it once per id at the caret it saved when the mic was pressed: the
   * text has to land in `ChatInput`'s own `message` state, which the hook
   * cannot reach.
   */
  transcript: { id: number; text: string } | null;
}

export interface DictationActions {
  /** Opens the mic via `mic.start()` and records; captures `agentId` at this moment. */
  start(): Promise<void>;
  /** Stop recording and transcribe what was said. */
  stop(): void;
  /** Discard everything, and abort a request in flight. */
  cancel(): void;
  /** Send the held recording again. */
  retry(): void;
  /** Clear a failure and drop the held recording. */
  dismiss(): void;
}

export interface UseDictationOptions {
  /** The microphone the composer's glow also listens to: one capture, shared. */
  mic: UseMicrophoneResult;
  /** The agent the recording is sent through, read when the mic is pressed. */
  agentId: string | null;
  /** The organization's longest dictation; the recording stops itself there. */
  maxSeconds: number;
  /**
   * The organization's speech-to-text provider, read when the mic is pressed.
   * It decides the format: a WAV file for one that does not take WebM or Opus.
   */
  provider: string | null;
}

/** One recording, whichever way it is made. */
interface Recorder {
  /** True from `start` until `stop`. */
  readonly recording: boolean;
  /** Throws when the stream has nothing left to record. */
  start(): void;
  /** Ends the recording; the recorder then hands over what it holds, once. */
  stop(): void;
}

/**
 * A `MediaRecorder` in the first type the browser and the server share, or
 * null where there is none. `done` receives the recording once it stops.
 */
function mediaRecorder(stream: MediaStream, done: (recording: Blob) => void): Recorder | null {
  const type =
    typeof MediaRecorder === "undefined"
      ? undefined
      : TYPES.find((candidate) => MediaRecorder.isTypeSupported(candidate));
  if (type === undefined) return null;
  let recorder: MediaRecorder;
  try {
    recorder = new MediaRecorder(stream, { mimeType: type, audioBitsPerSecond: BITS_PER_SECOND });
  } catch {
    // A type the browser said it supports and then refused to record.
    return null;
  }
  const chunks: Blob[] = [];
  recorder.addEventListener("dataavailable", (event) => chunks.push(event.data));
  recorder.addEventListener("stop", () => done(new Blob(chunks, { type })));
  return {
    get recording() {
      return recorder.state !== "inactive";
    },
    start: () => recorder.start(TIMESLICE_MS),
    stop: () => recorder.stop(),
  };
}

/**
 * A recorder that writes 16 kHz mono 16-bit WAV from the stream's raw samples,
 * or null where the page has no Web Audio. `done` receives the file on `stop`.
 *
 * A `ScriptProcessorNode`, deprecated, rather than an `AudioWorklet`: a worklet
 * is a separate module the page loads by URL, and the console's CSP has no
 * `worker-src`, so it falls to `script-src` - nonce and `'strict-dynamic'` -
 * which admits neither a `blob:` module nor a file outside the bundle. Every
 * browser still runs the processor, and it reads a few kilobytes of samples a
 * callback, which the main thread does not notice.
 */
function wavRecorder(stream: MediaStream, done: (recording: Blob) => void): Recorder | null {
  const context = getAudioContext();
  if (context === null) return null;
  const pcm: ArrayBuffer[] = [];
  let nodes: AudioNode[] = [];
  let recording = false;
  return {
    get recording() {
      return recording;
    },
    start() {
      // What `MediaRecorder.start` refuses with: a stream whose tracks ended.
      // i18n-exempt: caught by the hook and read as `mic_busy`, never shown
      if (!stream.active) throw new DOMException("The stream has ended.", "InvalidStateError");
      const resample = createResampler(context.sampleRate);
      const source = context.createMediaStreamSource(stream);
      const processor = context.createScriptProcessor(WAV_BUFFER_SIZE, 2, 1);
      // A processor only runs while connected to the destination; the gain at
      // zero keeps the microphone from playing back through the speakers.
      const mute = context.createGain();
      mute.gain.value = 0;
      processor.addEventListener("audioprocess", ({ inputBuffer }) => {
        const channels = Array.from({ length: inputBuffer.numberOfChannels }, (_, i) =>
          inputBuffer.getChannelData(i),
        );
        pcm.push(toPcm16(resample(mixToMono(channels))));
      });
      source.connect(processor);
      processor.connect(mute);
      mute.connect(context.destination);
      nodes = [source, processor, mute];
      recording = true;
    },
    stop() {
      recording = false;
      for (const node of nodes) node.disconnect();
      done(wavBlob(pcm));
    },
  };
}

/** A failure the hook knows, or `"mic"`: the browser refused, and `mic` says why. */
type Failure = DictationReason | "mic" | "mic_insecure" | "mic_busy";

/**
 * Why the microphone did not open, told apart because each has a different fix:
 * `mic_insecure` - this page cannot ask at all (plain HTTP on a host other than
 * localhost); `mic_denied` - the person or the system refused; `mic_not_found` -
 * the browser sees no input device, and then it never shows a prompt;
 * `mic_busy` - a device exists but would not start (another app holds it, or the
 * stream ended before recording).
 */
export type MicFailure = "mic_insecure" | "mic_denied" | "mic_not_found" | "mic_busy";

/** The browser's refusal, as one of the reasons above. */
function micFailure(mic: UseMicrophoneResult): MicFailure {
  const name = mic.error?.name;
  if (mic.state === "denied" || name === "NotAllowedError" || name === "SecurityError") {
    return "mic_denied";
  }
  if (name === "NotFoundError" || name === "OverconstrainedError") return "mic_not_found";
  return "mic_busy";
}

/**
 * Records the composer's microphone and turns the recording into text on the
 * organization's speech-to-text provider.
 *
 * It drives the caller's `mic` rather than opening its own, so the glow around
 * the composer and the recorder read one capture. Every way out - stop, cancel,
 * the auto-stop, the track ending, a failure, unmount - closes it, so the
 * browser's recording indicator goes off with the recording.
 *
 * A recording that ends by itself (the limit, or the device going away) is
 * transcribed, never thrown away: the person said it. One that fails in a way
 * that can succeed on a second try is held in memory until Retry, Discard or
 * unmount, and never stored anywhere.
 */
export function useDictation({ mic, agentId, maxSeconds, provider }: UseDictationOptions): {
  state: DictationState;
  actions: DictationActions;
} {
  const [phase, setPhase] = useState<DictationPhase>("idle");
  const [elapsed, setElapsed] = useState(0);
  const [silent, setSilent] = useState(false);
  const [level, setLevel] = useState(0);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [canRetry, setCanRetry] = useState(false);
  const [retryAfter, setRetryAfter] = useState<number | null>(null);
  const [transcript, setTranscript] = useState<DictationState["transcript"]>(null);

  // The latest of everything an async continuation reads: by the time a
  // `getUserMedia` prompt is answered the render it started in is long gone.
  const micRef = useRef(mic);
  const maxRef = useRef(maxSeconds);
  const providerRef = useRef(provider);
  useEffect(() => {
    micRef.current = mic;
    maxRef.current = maxSeconds;
    providerRef.current = provider;
  });

  /** Bumped by every start, cancel, dismiss and unmount; stale work checks it and stops. */
  const sessionRef = useRef(0);
  const phaseRef = useRef<DictationPhase>("idle");
  const agentRef = useRef<string | null>(null);
  const recorderRef = useRef<Recorder | null>(null);
  const blobRef = useRef<Blob | null>(null);
  /** How long the kept recording is, by the browser's clock - sent with it, and again on a retry. */
  const secondsRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);
  const transcriptIdRef = useRef(0);
  const retryAfterRef = useRef<number | null>(null);
  /** Tears down the recording's timers, frames, listeners and analyser. */
  const teardownRef = useRef<() => void>(() => {});
  const countdownRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const moveTo = useCallback((next: DictationPhase) => {
    phaseRef.current = next;
    setPhase(next);
  }, []);

  const clearCountdown = useCallback(() => {
    if (countdownRef.current !== null) clearInterval(countdownRef.current);
    countdownRef.current = null;
    retryAfterRef.current = null;
    setRetryAfter(null);
  }, []);

  const startCountdown = useCallback((seconds: number) => {
    retryAfterRef.current = seconds;
    setRetryAfter(seconds);
    countdownRef.current = setInterval(() => {
      const left = retryAfterRef.current! - 1;
      if (left > 0) {
        retryAfterRef.current = left;
        setRetryAfter(left);
        return;
      }
      clearInterval(countdownRef.current!);
      countdownRef.current = null;
      retryAfterRef.current = null;
      setRetryAfter(null);
    }, 1000);
  }, []);

  const send = useCallback(
    async (blob: Blob) => {
      const session = sessionRef.current;
      const controller = new AbortController();
      abortRef.current = controller;
      setFailure(null);
      setCanRetry(false);
      clearCountdown();
      moveTo("transcribing");
      try {
        const text = await dictate(agentRef.current!, blob, secondsRef.current, controller.signal);
        if (session !== sessionRef.current) return;
        blobRef.current = null;
        transcriptIdRef.current += 1;
        setTranscript({ id: transcriptIdRef.current, text });
        moveTo("idle");
      } catch (error) {
        if (session !== sessionRef.current) return;
        const reason = dictationReason(error);
        if (reason === null) {
          blobRef.current = null;
          moveTo("idle");
          return;
        }
        const keep = RETRYABLE.has(reason);
        if (!keep) blobRef.current = null;
        setFailure(reason);
        setCanRetry(keep);
        const wait = retryAfterSeconds(error);
        if (wait !== null) startCountdown(wait);
        moveTo("failed");
      } finally {
        if (abortRef.current === controller) abortRef.current = null;
      }
    },
    [clearCountdown, moveTo, startCountdown],
  );

  /** Watch the stream's level for the waveform and the silence hint. */
  const meter = useCallback((stream: MediaStream): (() => void) => {
    const context = getAudioContext();
    if (context === null) return () => {};
    const source = context.createMediaStreamSource(stream);
    const analyser = context.createAnalyser();
    analyser.fftSize = 1024;
    source.connect(analyser);
    const samples = new Float32Array(analyser.fftSize);
    let smoothed = 0;
    let lastPublished = 0;
    let quietSince = Date.now();
    let quiet = false;
    let frame = 0;
    const sample = () => {
      analyser.getFloatTimeDomainData(samples);
      let sum = 0;
      for (const value of samples) sum += value * value;
      const target = Math.min(1, Math.sqrt(sum / samples.length) * LEVEL_GAIN);
      smoothed += (target - smoothed) * (target > smoothed ? ATTACK : RELEASE);
      const now = Date.now();
      if (smoothed >= SILENCE_LEVEL) quietSince = now;
      const nowQuiet = now - quietSince >= SILENCE_MS;
      if (nowQuiet !== quiet) {
        quiet = nowQuiet;
        setSilent(nowQuiet);
      }
      if (now - lastPublished >= LEVEL_EVERY_MS) {
        lastPublished = now;
        setLevel(smoothed);
      }
      frame = requestAnimationFrame(sample);
    };
    frame = requestAnimationFrame(sample);
    return () => {
      cancelAnimationFrame(frame);
      source.disconnect();
      analyser.disconnect();
    };
  }, []);

  /** Close the recording's plumbing and the microphone with it. */
  const closeRecording = useCallback(() => {
    teardownRef.current();
    teardownRef.current = () => {};
    recorderRef.current = null;
    micRef.current.stop();
    setSilent(false);
    setLevel(0);
  }, []);

  const record = useCallback(
    (stream: MediaStream, session: number) => {
      const fail = (why: Failure) => {
        closeRecording();
        setFailure(why);
        moveTo("failed");
      };
      let startedAt = 0;
      const done = (blob: Blob) => {
        // A cancel or an unmount got here first: it closed everything, and what
        // was said is discarded. Closing again could close the next recording.
        if (session !== sessionRef.current) return;
        closeRecording();
        if (Date.now() - startedAt < MIN_SECONDS * 1000) {
          moveTo("too_short");
          return;
        }
        blobRef.current = blob;
        secondsRef.current = (Date.now() - startedAt) / 1000;
        void send(blob);
      };
      const open =
        providerRef.current !== null && WAV_PROVIDERS.has(providerRef.current)
          ? wavRecorder
          : mediaRecorder;
      const recorder = open(stream, done);
      if (recorder === null) {
        fail("unsupported_type");
        return;
      }
      startedAt = Date.now();

      const finish = () => {
        if (recorder.recording) recorder.stop();
      };
      const tick = setInterval(() => {
        const seconds = Math.floor((Date.now() - startedAt) / 1000);
        setElapsed(seconds);
        if (seconds >= maxRef.current) finish();
      }, 1000);
      // The device went away or the permission was revoked mid-sentence: what
      // was recorded up to here is still the person's dictation.
      const tracks = stream.getAudioTracks();
      for (const track of tracks) track.addEventListener("ended", finish);
      const stopMeter = meter(stream);
      teardownRef.current = () => {
        clearInterval(tick);
        for (const track of tracks) track.removeEventListener("ended", finish);
        stopMeter();
      };

      recorderRef.current = recorder;
      try {
        recorder.start();
      } catch {
        // The track ended between the prompt and here: there is nothing to record.
        fail("mic_busy");
        return;
      }
      moveTo("recording");
    },
    [closeRecording, meter, moveTo, send],
  );

  const start = useCallback(async () => {
    const current = phaseRef.current;
    if (current === "requesting" || current === "recording" || current === "transcribing") return;
    if (agentId === null) return;
    const session = ++sessionRef.current;
    agentRef.current = agentId;
    blobRef.current = null;
    clearCountdown();
    setFailure(null);
    setCanRetry(false);
    setElapsed(0);
    setSilent(false);
    setLevel(0);
    if (!micRef.current.supported) {
      setFailure("mic_insecure");
      moveTo("failed");
      return;
    }
    moveTo("requesting");
    const stream = await micRef.current.start();
    if (session !== sessionRef.current) {
      // Cancelled while the browser was asking; the prompt was answered anyway.
      if (stream !== null) micRef.current.stop();
      return;
    }
    if (stream === null) {
      setFailure("mic");
      moveTo("failed");
      return;
    }
    record(stream, session);
  }, [agentId, clearCountdown, moveTo, record]);

  const stop = useCallback(() => {
    const recorder = recorderRef.current;
    if (recorder !== null && recorder.recording) recorder.stop();
  }, []);

  /** Forget the recording and any request for it, and close the microphone. */
  const abandon = useCallback(() => {
    sessionRef.current += 1;
    abortRef.current?.abort();
    abortRef.current = null;
    const recorder = recorderRef.current;
    if (recorder !== null && recorder.recording) recorder.stop();
    closeRecording();
    blobRef.current = null;
    clearCountdown();
  }, [clearCountdown, closeRecording]);

  const cancel = useCallback(() => {
    abandon();
    setFailure(null);
    setCanRetry(false);
    moveTo("idle");
  }, [abandon, moveTo]);

  const dismiss = cancel;

  const retry = useCallback(() => {
    const blob = blobRef.current;
    if (phaseRef.current !== "failed" || blob === null) return;
    if (retryAfterRef.current !== null) return;
    void send(blob);
  }, [send]);

  // `abandon` never changes identity, so this runs its cleanup on unmount only.
  useEffect(() => abandon, [abandon]);

  const remainingSeconds = maxSeconds - elapsed;
  const reason: DictationState["reason"] = failure === "mic" ? micFailure(mic) : failure;

  // The strip says what to do; the console keeps what the browser actually said,
  // which is the one thing anybody debugging a microphone needs to see.
  const micError = failure === "mic" ? mic.error : null;
  useEffect(() => {
    if (micError)
      // i18n-exempt: a developer's console line, never shown in the page
      console.warn("Dictation: the microphone did not open:", micError);
  }, [micError]);

  return {
    state: {
      phase,
      elapsed,
      remaining:
        phase === "recording" && remainingSeconds <= WARN_SECONDS
          ? Math.max(0, remainingSeconds)
          : null,
      silent,
      level,
      reason,
      canRetry,
      retryAfter,
      transcript,
    },
    actions: { start, stop, cancel, retry, dismiss },
  };
}
