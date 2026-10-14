"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";

import { usePublicConfig } from "@/components/public-config/public-config-provider";
import {
  callReducer,
  initialCall,
  type CallState,
  type MicFailure,
} from "@/lib/voice/call-reducer";
import { audioOnlyOffer, consoleVoiceUrl, embedVoiceUrl } from "@/lib/voice/sdp";
import { useAuthStore, useOrgStore, useVoiceCallStore } from "@/stores";
import type { VoiceClientFrame, VoiceServerFrame } from "@/types/voice";

export type VoiceTarget =
  | { kind: "console"; agentId: string; conversationId: string | null }
  | { kind: "embed"; publicKey: string; visitorKey: string | null; token: string | null };

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
 * guarantee. Relay transport (Gemini, xAI, Azure) is added with slice 1.
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

  /** Close the socket without its close handler deciding anything, and the media with it. */
  const closeAll = useCallback(() => {
    cancelRetry();
    const socket = socketRef.current;
    socketRef.current = null;
    socket?.close();
    pcRef.current?.close();
    pcRef.current = null;
    micRef.current?.getTracks().forEach((track) => track.stop());
    micRef.current = null;
    setLocalStream(null);
    setRemoteStream(null);
  }, [cancelRetry]);

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

  const connect = useCallback(
    async (attempt: Attempt) => {
      const { target, generation, resume } = attempt;
      const pc = new RTCPeerConnection();
      pcRef.current = pc;
      const mic = micRef.current as MediaStream;
      mic.getAudioTracks().forEach((track) => pc.addTrack(track, mic));
      pc.ontrack = (event) => setRemoteStream(event.streams[0] ?? null);
      const sdp = await audioOnlyOffer(pc);
      if (!current(generation)) {
        pc.close();
        return;
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
      // Whether this connection was set up; a resume that never was is tried again.
      let ready = false;
      socket.onopen = () => {
        const start: VoiceClientFrame = {
          type: "start",
          sdp_offer: sdp,
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
        const frame = JSON.parse(event.data as string) as VoiceServerFrame;
        // After End only the server's own account of the end, and the turns it
        // saved on the way out, still count; nothing may bring the call back.
        if (!liveRef.current && frame.type !== "ended" && frame.type !== "turn_saved") return;
        if (frame.type === "answer") {
          pc.setRemoteDescription({ type: "answer", sdp: frame.sdp }).catch(() => {
            if (current(generation)) giveUp();
          });
        }
        if (frame.type === "ready") {
          ready = true;
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
        pc.close();
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
    [activeOrgId, applyTrack, closeAll, giveUp, scheduleResume, wsUrl],
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
      pcRef.current?.close();
      pcRef.current = null;
      micRef.current?.getTracks().forEach((track) => track.stop());
      micRef.current = null;
      setLocalStream(null);
      setRemoteStream(null);
    } else {
      // Still connecting: never let it open and start a call nobody is on.
      closeAll();
    }
    dispatch({ type: "frame", frame: { type: "ended", reason: "user" }, now: Date.now() });
  }, [cancelRetry, closeAll]);

  const start = useCallback(
    async (target: VoiceTarget) => {
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
