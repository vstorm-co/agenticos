"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { getAudioContext } from "voice-glow";

import { usePublicConfig } from "@/components/public-config/public-config-provider";
import { micFailure } from "@/hooks/use-dictation";
import { callReducer, initialCall, type CallState } from "@/lib/voice/call-reducer";
import {
  createPcmCapture,
  createPcmPlayer,
  PLAYED_EVERY_MS,
  type PcmCapture,
  type PcmPlayer,
} from "@/lib/voice/pcm";
import { audioOnlyOffer, consoleVoiceUrl, embedVoiceUrl } from "@/lib/voice/sdp";
import { useAuthStore, useOrgStore, useVoiceCallStore } from "@/stores";
import type { AskUserAnswer } from "@/types/chat";
import type {
  VoiceClientFrame,
  VoiceSavedTurn,
  VoiceServerFrame,
  VoiceStartContext,
  VoiceTransport,
} from "@/types/voice";

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
      /**
       * What the page says about the visitor - the `context` its typed messages
       * carry - sent with every `start`, a resumed one included, so a call is
       * briefed as text chat is. The server keeps only the embed's declared variables.
       */
      context?: VoiceStartContext;
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
 * server accepts `resume_of`, with that connection's `resume_token`, for 10 s
 * after the previous connection was closed; this stops short of it, so the last
 * attempt still lands inside that window.
 */
export const RESUME_WINDOW_MS = 8000;

const MIC_CONSTRAINTS: MediaStreamConstraints = {
  audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
};

/** One connection of a call: a fresh one, or the one automatic retry resuming it. */
interface Attempt {
  target: VoiceTarget;
  /** Which `start` this belongs to; a later `start` makes every older attempt stale. */
  generation: number;
  /**
   * The call this connection resumes, the token its `ready` gave this caller,
   * and until when the retry keeps trying.
   */
  resume: { of: string; token: string; until: number } | null;
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
  /** Answer the questions card the call is waiting on; the server closes it. */
  answer: (questionsId: string, answers: AskUserAnswer[]) => void;
  dismissUnavailable: () => void;
  /** Forget an ended call: its summary, or why it could not start. A live call is left alone. */
  dismiss: () => void;
}

/** After End, how long the socket stays open for the turns the server saves on the way out. */
const END_LINGER_MS = 5000;

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
  options: {
    /** A turn was saved as a message: the message, as the server saved it. */
    onTurnSaved?: (message: VoiceSavedTurn) => void;
    onConversation?: (id: string) => void;
  } = {},
): VoiceSession {
  const [call, dispatch] = useReducer(callReducer, initialCall);
  const [localStream, setLocalStream] = useState<MediaStream | null>(null);
  const [remoteStream, setRemoteStream] = useState<MediaStream | null>(null);
  const { wsUrl } = usePublicConfig();
  const pushToTalk = useVoiceCallStore((state) => state.pushToTalk);

  const socketRef = useRef<WebSocket | null>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const relayRef = useRef<RelayMedia | null>(null);
  const micRef = useRef<MediaStream | null>(null);
  // What resumes this call after a drop: its id and the token its `ready` gave.
  const resumableRef = useRef<{ of: string; token: string } | null>(null);
  const conversationRef = useRef<string | null>(null);
  // Cancels the retry waiting to run - its timer and its `online` listener.
  const cancelRetryRef = useRef<(() => void) | null>(null);
  // A call is live from `start` until it ends - by End, by the server, or by
  // a drop with no retry left. Every await re-checks it with the generation:
  // End can be pressed, and another call started, while the browser is still
  // asking for the microphone.
  const liveRef = useRef(false);
  const generationRef = useRef(0);
  const ownerRef = useRef<{ organizationId: string | null; userId: string | null } | null>(null);
  const retriedRef = useRef(false);
  const mutedRef = useRef(false);
  const optionsRef = useRef(options);
  useEffect(() => {
    optionsRef.current = options;
  });
  // The retry calls `connect` from inside `connect`'s own close handler.
  const connectRef = useRef<((attempt: Attempt) => Promise<void>) | null>(null);

  const owned = useCallback((generation: number) => {
    const owner = ownerRef.current;
    return (
      generationRef.current === generation &&
      (owner === null ||
        (owner.organizationId === useOrgStore.getState().activeOrgId &&
          owner.userId === (useAuthStore.getState().user?.id ?? null)))
    );
  }, []);
  const current = useCallback(
    (generation: number) => liveRef.current && owned(generation),
    [owned],
  );

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

  /** Stop the call's media and the microphone: what every way a call ends lets go of. */
  const releaseMedia = useCallback(() => {
    closeMedia();
    micRef.current?.getTracks().forEach((track) => track.stop());
    micRef.current = null;
    setLocalStream(null);
    setRemoteStream(null);
  }, [closeMedia]);

  /** Close the socket without its close handler deciding anything, and the media with it. */
  const closeAll = useCallback(() => {
    cancelRetry();
    const socket = socketRef.current;
    socketRef.current = null;
    socket?.close();
    releaseMedia();
  }, [cancelRetry, releaseMedia]);

  // Store subscriptions invalidate ownership synchronously, including while a
  // browser permission prompt or reconnect timer is pending. Public embeds own
  // their visitor scope and do not follow the console's account or tenant.
  useEffect(() => {
    const invalidate = () => {
      const owner = ownerRef.current;
      if (owner === null || owned(generationRef.current)) return;
      ++generationRef.current;
      ownerRef.current = null;
      liveRef.current = false;
      resumableRef.current = null;
      conversationRef.current = null;
      closeAll();
      dispatch({ type: "reset" });
    };
    const unsubscribeOrg = useOrgStore.subscribe(invalidate);
    const unsubscribeAuth = useAuthStore.subscribe(invalidate);
    return () => {
      unsubscribeOrg();
      unsubscribeAuth();
    };
  }, [closeAll, owned]);

  const giveUp = useCallback(() => {
    liveRef.current = false;
    dispatch({ type: "socket_lost", willRetry: false });
    closeAll();
  }, [closeAll]);

  /**
   * The peer connection failed - ICE found no path, as on a network that blocks
   * UDP. The socket may still be open and the server still billing for a call
   * nobody can hear, so the call ends here: closing the socket ends it there.
   */
  const mediaFailed = useCallback(() => {
    liveRef.current = false;
    dispatch({ type: "media_failed", now: Date.now() });
    closeAll();
  }, [closeAll]);

  /** Run the retry after `delay`, or as soon as the browser is back online. */
  const scheduleResume = useCallback(
    (attempt: Attempt, delay: number) => {
      const run = () => {
        cancelRetry();
        if (!current(attempt.generation)) return;
        (connectRef.current as (next: Attempt) => Promise<void>)(attempt).catch(() => {
          if (current(attempt.generation)) giveUp();
        });
      };
      const timer = window.setTimeout(run, delay);
      window.addEventListener("online", run);
      cancelRetryRef.current = () => {
        window.clearTimeout(timer);
        window.removeEventListener("online", run);
      };
    },
    [cancelRetry, current, giveUp],
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
        peer.ontrack = (event) => {
          if (owned(generation) && pcRef.current === peer)
            setRemoteStream(event.streams[0] ?? null);
        };
        const watch = () => {
          if (pcRef.current !== peer || !current(generation)) return;
          if (peer.connectionState === "failed" || peer.iceConnectionState === "failed") {
            mediaFailed();
          }
        };
        peer.onconnectionstatechange = watch;
        peer.oniceconnectionstatechange = watch;
        sdp = await audioOnlyOffer(peer);
        if (!current(generation)) {
          peer.close();
          return;
        }
      }
      const url =
        target.kind === "console"
          ? consoleVoiceUrl(wsUrl, ownerRef.current?.organizationId ?? null)
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
        if (!current(generation) || socketRef.current !== socket) {
          socket.close();
          return;
        }
        const start: VoiceClientFrame = {
          type: "start",
          ...(sdp !== null ? { sdp_offer: sdp } : {}),
          ...(target.kind === "console"
            ? { agent_id: target.agentId, conversation_id: conversationRef.current }
            : {}),
          ...(target.kind === "embed" && target.context ? { context: target.context } : {}),
          ...(resume ? { resume_of: resume.of, resume_token: resume.token } : {}),
        };
        socket.send(JSON.stringify(start));
        applyTrack(false);
      };
      socket.onmessage = (event: MessageEvent) => {
        if (!owned(generation)) return;
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
          resumableRef.current = { of: frame.call_id, token: frame.resume_token };
          // A resumed connection starts unmuted on the server; a caller who
          // muted before the drop is still muted here.
          if (mutedRef.current) {
            socket.send(JSON.stringify({ type: "mute", muted: true } satisfies VoiceClientFrame));
          }
          if (conversationRef.current !== frame.conversation_id) {
            conversationRef.current = frame.conversation_id;
            optionsRef.current.onConversation?.(frame.conversation_id);
          }
        }
        if (frame.type === "turn_saved") optionsRef.current.onTurnSaved?.(frame.message);
        if (frame.type === "ended") {
          // Over on the server: the media goes now. The socket stays for the
          // turns still being saved, until the server closes it.
          liveRef.current = false;
          cancelRetry();
          releaseMedia();
        }
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
        const resumable = resumableRef.current;
        if (resumable === null || retriedRef.current) {
          giveUp();
          return;
        }
        retriedRef.current = true;
        dispatch({ type: "socket_lost", willRetry: true });
        scheduleResume(
          { target, generation, resume: { ...resumable, until: Date.now() + RESUME_WINDOW_MS } },
          RECONNECT_DELAY_MS,
        );
      };
    },
    [
      applyTrack,
      current,
      owned,
      cancelRetry,
      closeAll,
      closeMedia,
      giveUp,
      mediaFailed,
      releaseMedia,
      scheduleResume,
      startRelay,
      wsUrl,
    ],
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
      releaseMedia();
      // Open a moment longer for the turns saved on the way out, then closed
      // whatever the server did: this socket, not whichever a new call opened.
      window.setTimeout(() => {
        if (socketRef.current === socket) socketRef.current = null;
        socket.close();
      }, END_LINGER_MS);
    } else {
      // Still connecting: never let it open and start a call nobody is on.
      closeAll();
    }
    dispatch({ type: "frame", frame: { type: "ended", reason: "user" }, now: Date.now() });
  }, [cancelRetry, closeAll, releaseMedia]);

  const start = useCallback(
    async (target: VoiceTarget) => {
      // Safari starts an AudioContext only inside the gesture that asked for it,
      // and `ready` arrives long after the click: create (and resume) it now.
      if (target.transport === "relay") getAudioContext();
      // One call at a time: a call still live is ended, and every await below
      // gives up if another `start` has run since.
      end();
      const generation = ++generationRef.current;
      ownerRef.current =
        target.kind === "console"
          ? {
              organizationId: useOrgStore.getState().activeOrgId,
              userId: useAuthStore.getState().user?.id ?? null,
            }
          : null;
      liveRef.current = true;
      retriedRef.current = false;
      mutedRef.current = false;
      resumableRef.current = null;
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
      await connect({ target, generation, resume: null }).catch(() => {
        if (current(generation)) giveUp();
      });
    },
    [connect, current, end, giveUp],
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

  const pressToTalk = useCallback((down: boolean) => applyTrack(down), [applyTrack]);

  const decide = useCallback(
    (approvalId: string, approve: boolean) =>
      send({ type: "approval", id: approvalId, decision: approve ? "approve" : "deny" }),
    [send],
  );

  const answer = useCallback(
    (questionsId: string, answers: AskUserAnswer[]) =>
      send({ type: "answers", id: questionsId, answers }),
    [send],
  );

  const dismissUnavailable = useCallback(() => dispatch({ type: "dismiss_unavailable" }), []);

  const dismiss = useCallback(() => {
    if (!liveRef.current) dispatch({ type: "reset" });
  }, []);

  return {
    call,
    localStream,
    remoteStream,
    start,
    end,
    setMuted,
    pressToTalk,
    decide,
    answer,
    dismissUnavailable,
    dismiss,
  };
}
