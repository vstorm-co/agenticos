"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { getAudioContext } from "voice-glow";

import { usePublicConfig } from "@/components/public-config/public-config-provider";
import {
  callReducer,
  initialCall,
  type CallState,
  type MicFailure,
} from "@/lib/voice/call-reducer";
import {
  createPcmCapture,
  createPcmPlayer,
  PLAYED_EVERY_MS,
  type PcmCapture,
  type PcmPlayer,
} from "@/lib/voice/pcm";
import { audioOnlyOffer, consoleVoiceUrl, embedVoiceUrl } from "@/lib/voice/sdp";
import { useAuthStore, useOrgStore, useVoiceCallStore } from "@/stores";
import type { VoiceClientFrame, VoiceServerFrame, VoiceTransport } from "@/types/voice";

/**
 * Who to call, and how the call's audio travels - the agent's readiness says
 * (`GET /agents/{id}/voice`): `webrtc` straight to the provider, `relay` through
 * the voice socket.
 */
export type VoiceTarget =
  | { kind: "console"; agentId: string; conversationId: string | null; transport: VoiceTransport }
  | {
      kind: "embed";
      publicKey: string;
      visitorKey: string | null;
      token: string | null;
      transport: VoiceTransport;
    };

/** A relayed call's audio in this page: the capture, the player and its `played` reports. */
interface RelayMedia {
  capture: PcmCapture;
  player: PcmPlayer;
  timer: number;
}

/** How long the one automatic retry waits, so the old connection's teardown has finished. */
export const RECONNECT_DELAY_MS = 1500;

/**
 * How long after a drop the retry keeps trying to open the resumed socket. The
 * server accepts `resume_of` for 10 s after the previous connection ended; this
 * stops short of it, so the last attempt still lands inside that window.
 */
export const RESUME_WINDOW_MS = 8000;

const MIC_CONSTRAINTS: MediaStreamConstraints = {
  audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
};

/** The browser's refusal, told apart the way dictation tells it (`use-dictation.ts`). */
function micFailure(error: unknown): MicFailure {
  const name = error instanceof Error ? error.name : "";
  if (name === "NotAllowedError" || name === "SecurityError") return "mic_denied";
  if (name === "NotFoundError" || name === "OverconstrainedError") return "mic_not_found";
  return "mic_busy";
}

/** One connection of a call: a fresh one, or the one automatic retry resuming it. */
interface Attempt {
  target: VoiceTarget;
  /** Which `start` this belongs to; a later `start` makes every older attempt stale. */
  generation: number;
  /** The call this connection resumes, and until when the retry keeps trying. */
  resume: { of: string; until: number } | null;
}

export interface VoiceSession {
  call: CallState;
  localStream: MediaStream | null;
  remoteStream: MediaStream | null;
  start: (target: VoiceTarget) => Promise<void>;
  end: () => void;
  setMuted: (muted: boolean) => void;
  pressToTalk: (down: boolean) => void;
  decide: (approvalId: string, approve: boolean) => void;
  dismissUnavailable: () => void;
}

/**
 * One voice call from this page (#54): the microphone, the peer connection, the
 * socket that governs them, and one automatic reconnect.
 *
 * The socket is the call: when it closes, the peer connection is closed and the
 * microphone stopped. Closing them on `pagehide` and on unmount too is a
 * courtesy - the server's hang-up in its `finally` and its reaper are the
 * guarantee.
 *
 * A relayed call (Gemini, xAI, Azure; not verified live) has no peer
 * connection: once the server is `ready` the microphone is sent as PCM at the
 * model's input rate, the agent's audio is played from binary frames, how much
 * of it was played is reported every {@link PLAYED_EVERY_MS}, and
 * `clear_playback` drops what is queued - the browser's half of barge-in.
 * Mute and push-to-talk disable the track, which captures as silence.
 *
 * A drop is retried once, as one logical retry: the resumed socket is opened
 * again until {@link RESUME_WINDOW_MS} after the drop (sooner when the browser
 * says it is back `online`), and only then is the call shown as dropped.
 */
export function useVoiceSession(
  options: { onTurnSaved?: () => void; onConversation?: (id: string) => void } = {},
): VoiceSession {
  const [call, dispatch] = useReducer(callReducer, initialCall);
  const [localStream, setLocalStream] = useState<MediaStream | null>(null);
  const [remoteStream, setRemoteStream] = useState<MediaStream | null>(null);
  const { wsUrl } = usePublicConfig();
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const pushToTalk = useVoiceCallStore((state) => state.pushToTalk);

  const socketRef = useRef<WebSocket | null>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const relayRef = useRef<RelayMedia | null>(null);
  const micRef = useRef<MediaStream | null>(null);
  const callIdRef = useRef<string | null>(null);
  const conversationRef = useRef<string | null>(null);
  // Cancels the retry waiting to run - its timer and its `online` listener.
  const cancelRetryRef = useRef<(() => void) | null>(null);
  // A call is live from `start` until it ends - by End, by the server, or by
  // a drop with no retry left. Every await re-checks it with the generation:
  // End can be pressed, and another call started, while the browser is still
  // asking for the microphone.
  const liveRef = useRef(false);
  const generationRef = useRef(0);
  const retriedRef = useRef(false);
  const mutedRef = useRef(false);
  const optionsRef = useRef(options);
  useEffect(() => {
    optionsRef.current = options;
  });
  // The retry calls `connect` from inside `connect`'s own close handler.
  const connectRef = useRef<((attempt: Attempt) => Promise<void>) | null>(null);

  const current = (generation: number) => liveRef.current && generationRef.current === generation;

  const send = useCallback((frame: VoiceClientFrame) => {
    const socket = socketRef.current;
    if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(frame));
  }, []);

  const applyTrack = useCallback((held: boolean) => {
    const track = micRef.current?.getAudioTracks()[0];
    if (track) {
      track.enabled = !mutedRef.current && (!useVoiceCallStore.getState().pushToTalk || held);
    }
  }, []);

  const cancelRetry = useCallback(() => {
    cancelRetryRef.current?.();
    cancelRetryRef.current = null;
  }, []);

  /** Stop this connection's media: the peer connection, or the relay's capture and player. */
  const closeMedia = useCallback(() => {
    pcRef.current?.close();
    pcRef.current = null;
    const relay = relayRef.current;
    relayRef.current = null;
    if (relay) {
      window.clearInterval(relay.timer);
      relay.capture.stop();
      relay.player.close();
    }
  }, []);

  /** Close the socket without its close handler deciding anything, and the media with it. */
  const closeAll = useCallback(() => {
    cancelRetry();
    const socket = socketRef.current;
    socketRef.current = null;
    socket?.close();
    closeMedia();
    micRef.current?.getTracks().forEach((track) => track.stop());
    micRef.current = null;
    setLocalStream(null);
    setRemoteStream(null);
  }, [cancelRetry, closeMedia]);

  const giveUp = useCallback(() => {
    liveRef.current = false;
    dispatch({ type: "socket_lost", willRetry: false });
    closeAll();
  }, [closeAll]);

  /** Run the retry after `delay`, or as soon as the browser is back online. */
  const scheduleResume = useCallback(
    (attempt: Attempt, delay: number) => {
      const run = () => {
        cancelRetry();
        (connectRef.current as (next: Attempt) => Promise<void>)(attempt).catch(giveUp);
      };
      const timer = window.setTimeout(run, delay);
      window.addEventListener("online", run);
      cancelRetryRef.current = () => {
        window.clearTimeout(timer);
        window.removeEventListener("online", run);
      };
    },
    [cancelRetry, giveUp],
  );

  /**
   * Start a relayed call's audio once the server says at which rates. `false`
   * when this browser has no Web Audio to capture or play with - the call is
   * given up, and its socket closed, which ends it on the server.
   */
  const startRelay = useCallback(
    (socket: WebSocket, frame: Extract<VoiceServerFrame, { type: "ready" }>): boolean => {
      const context = getAudioContext();
      if (context === null) {
        giveUp();
        return false;
      }
      const capture = createPcmCapture(
        context,
        micRef.current as MediaStream,
        frame.input_sample_rate,
        (pcm) => {
          if (socket.readyState === WebSocket.OPEN) socket.send(pcm);
        },
      );
      // Only a position that moved is sent: a quiet call sends nothing.
      let reported = 0;
      const report = () => {
        const bytes = player.playedBytes();
        if (bytes === reported || socket.readyState !== WebSocket.OPEN) return;
        reported = bytes;
        socket.send(JSON.stringify({ type: "played", bytes } satisfies VoiceClientFrame));
      };
      const player = createPcmPlayer(context, frame.output_sample_rate, report);
      const timer = window.setInterval(report, PLAYED_EVERY_MS);
      relayRef.current = { capture, player, timer };
      setRemoteStream(player.stream);
      return true;
    },
    [giveUp],
  );

  const connect = useCallback(
    async (attempt: Attempt) => {
      const { target, generation, resume } = attempt;
      const relayed = target.transport === "relay";
      let pc: RTCPeerConnection | null = null;
      let sdp: string | null = null;
      if (!relayed) {
        const peer = new RTCPeerConnection();
        pc = peer;
        pcRef.current = peer;
        const mic = micRef.current as MediaStream;
        mic.getAudioTracks().forEach((track) => peer.addTrack(track, mic));
        peer.ontrack = (event) => setRemoteStream(event.streams[0] ?? null);
        sdp = await audioOnlyOffer(peer);
        if (!current(generation)) {
          peer.close();
          return;
        }
      }
      const url =
        target.kind === "console"
          ? consoleVoiceUrl(wsUrl, activeOrgId)
          : embedVoiceUrl(wsUrl, target.publicKey, target.visitorKey, target.token);
      const token = useAuthStore.getState().accessToken;
      const socket =
        target.kind === "console" && token
          ? new WebSocket(url, [`access_token.${token}`, "voice"])
          : new WebSocket(url);
      socketRef.current = socket;
      // The agent's audio arrives as binary frames; an ArrayBuffer is what the player takes.
      if (relayed) socket.binaryType = "arraybuffer";
      // Whether this connection was set up; a resume that never was is tried again.
      let ready = false;
      socket.onopen = () => {
        const start: VoiceClientFrame = {
          type: "start",
          ...(sdp !== null ? { sdp_offer: sdp } : {}),
          ...(target.kind === "console"
            ? { agent_id: target.agentId, conversation_id: conversationRef.current }
            : {}),
          ...(resume ? { resume_of: resume.of } : {}),
        };
        socket.send(JSON.stringify(start));
        applyTrack(false);
      };
      socket.onmessage = (event: MessageEvent) => {
        if (generationRef.current !== generation) return;
        if (typeof event.data !== "string") {
          relayRef.current?.player.enqueue(event.data as ArrayBuffer);
          return;
        }
        const frame = JSON.parse(event.data) as VoiceServerFrame;
        // After End only the server's own account of the end, and the turns it
        // saved on the way out, still count; nothing may bring the call back.
        if (!liveRef.current && frame.type !== "ended" && frame.type !== "turn_saved") return;
        if (frame.type === "answer" && pc !== null) {
          pc.setRemoteDescription({ type: "answer", sdp: frame.sdp }).catch(() => {
            if (current(generation)) giveUp();
          });
        }
        if (frame.type === "clear_playback") relayRef.current?.player.clear();
        if (frame.type === "ready") {
          if (frame.transport !== target.transport) {
            // The agent was re-published onto another transport between its
            // readiness and this call: this connection cannot carry the audio.
            giveUp();
            return;
          }
          ready = true;
          if (relayed && relayRef.current === null && !startRelay(socket, frame)) return;
          callIdRef.current = frame.call_id;
          if (conversationRef.current !== frame.conversation_id) {
            conversationRef.current = frame.conversation_id;
            optionsRef.current.onConversation?.(frame.conversation_id);
          }
        }
        if (frame.type === "turn_saved") optionsRef.current.onTurnSaved?.();
        if (frame.type === "ended") liveRef.current = false;
        dispatch({ type: "frame", frame, now: Date.now() });
      };
      socket.onclose = () => {
        if (socketRef.current !== socket) return;
        socketRef.current = null;
        closeMedia();
        if (!liveRef.current) {
          closeAll();
          return;
        }
        if (resume !== null && !ready && Date.now() < resume.until) {
          // The resumed socket did not get through yet; the window is still open.
          scheduleResume(attempt, RECONNECT_DELAY_MS);
          return;
        }
        const callId = callIdRef.current;
        if (callId === null || retriedRef.current) {
          giveUp();
          return;
        }
        retriedRef.current = true;
        dispatch({ type: "socket_lost", willRetry: true });
        scheduleResume(
          { target, generation, resume: { of: callId, until: Date.now() + RESUME_WINDOW_MS } },
          RECONNECT_DELAY_MS,
        );
      };
    },
    [activeOrgId, applyTrack, closeAll, closeMedia, giveUp, scheduleResume, startRelay, wsUrl],
  );

  useEffect(() => {
    connectRef.current = connect;
  }, [connect]);

  const end = useCallback(() => {
    if (!liveRef.current) return;
    liveRef.current = false;
    cancelRetry();
    const socket = socketRef.current;
    if (socket?.readyState === WebSocket.OPEN) {
      // The server ends the call and closes the socket; its `ended` frame follows.
      socket.send(JSON.stringify({ type: "end" } satisfies VoiceClientFrame));
      closeMedia();
      micRef.current?.getTracks().forEach((track) => track.stop());
      micRef.current = null;
      setLocalStream(null);
      setRemoteStream(null);
    } else {
      // Still connecting: never let it open and start a call nobody is on.
      closeAll();
    }
    dispatch({ type: "frame", frame: { type: "ended", reason: "user" }, now: Date.now() });
  }, [cancelRetry, closeAll, closeMedia]);

  const start = useCallback(
    async (target: VoiceTarget) => {
      // Safari starts an AudioContext only inside the gesture that asked for it,
      // and `ready` arrives long after the click: create (and resume) it now.
      if (target.transport === "relay") getAudioContext();
      // One call at a time: a call still live is ended, and every await below
      // gives up if another `start` has run since.
      end();
      const generation = ++generationRef.current;
      liveRef.current = true;
      retriedRef.current = false;
      mutedRef.current = false;
      callIdRef.current = null;
      conversationRef.current = target.kind === "console" ? target.conversationId : null;
      dispatch({ type: "connecting" });
      // No `mediaDevices` at all is a page the browser will not let ask (plain
      // HTTP off localhost) - dictation's `mic_insecure`.
      if (!navigator.mediaDevices?.getUserMedia) {
        liveRef.current = false;
        dispatch({ type: "mic_failed", failure: "mic_insecure" });
        return;
      }
      let mic: MediaStream;
      try {
        mic = await navigator.mediaDevices.getUserMedia(MIC_CONSTRAINTS);
      } catch (error) {
        if (!current(generation)) return;
        liveRef.current = false;
        dispatch({ type: "mic_failed", failure: micFailure(error) });
        return;
      }
      if (!current(generation)) {
        // Ended, or replaced, while the browser was asking; the prompt was answered anyway.
        mic.getTracks().forEach((track) => track.stop());
        return;
      }
      micRef.current = mic;
      setLocalStream(mic);
      await connect({ target, generation, resume: null }).catch(giveUp);
    },
    [connect, end, giveUp],
  );

  useEffect(() => {
    window.addEventListener("pagehide", end);
    return () => {
      window.removeEventListener("pagehide", end);
      end();
    };
  }, [end]);

  useEffect(() => applyTrack(false), [pushToTalk, applyTrack]);

  const setMuted = useCallback(
    (muted: boolean) => {
      mutedRef.current = muted;
      applyTrack(false);
      send({ type: "mute", muted });
      dispatch({ type: "muted", muted });
    },
    [applyTrack, send],
  );

  const pressToTalk = useCallback(
    (down: boolean) => {
      applyTrack(down);
      send({ type: "ptt", state: down ? "down" : "up" });
    },
    [applyTrack, send],
  );

  const decide = useCallback(
    (approvalId: string, approve: boolean) =>
      send({ type: "approval", id: approvalId, decision: approve ? "approve" : "deny" }),
    [send],
  );

  const dismissUnavailable = useCallback(() => dispatch({ type: "dismiss_unavailable" }), []);

  return {
    call,
    localStream,
    remoteStream,
    start,
    end,
    setMuted,
    pressToTalk,
    decide,
    dismissUnavailable,
  };
}
