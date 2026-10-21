"use client";

import { useEffect, useMemo } from "react";

import { useMicrophone } from "@/components/ui/voice-glow";
import { useDictation } from "@/hooks/use-dictation";
import { useDictationStatus } from "@/hooks/use-dictation-status";
import { useOrganizationList } from "@/hooks/use-organizations";
import { dictate, type DictationSend } from "@/lib/dictation-api";
import { useOrgStore } from "@/stores/org-store";

/**
 * The browser's voice processing, on for a recording that is transcribed: echo
 * cancellation, noise suppression and gain control are what a speech model
 * wants. The glow-only capture keeps them off so it sees the voice's real
 * dynamics.
 */
const DICTATION_CONSTRAINTS = {
  constraints: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
};
/** The organization's longest dictation when its settings have not loaded. */
const DEFAULT_DICTATION_SECONDS = 300;

/**
 * Dictation into a message for one agent: the chat's composer, and the desktop
 * app's quick ask (#2305).
 *
 * The engine and the format are the agent's: its Dictation switch sends the
 * recording to a provider when one resolves, and the backend says what to
 * record for it - WAV, unless the deployment accepts compressed audio and that
 * provider takes WebM. The browser's own recognition until it answers. The
 * organization sets the longest recording.
 */
export function useAgentDictation(agentId: string | null) {
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const { data: orgs } = useOrganizationList();
  const activeOrg = orgs?.find((org) => org.id === activeOrgId) ?? null;
  const maxSeconds = activeOrg?.dictation_max_seconds ?? DEFAULT_DICTATION_SECONDS;
  const { status, failed } = useDictationStatus(agentId);
  const engine = status?.engine ?? "browser";
  // Opened by the microphone button; the glow around the box reads its level.
  // With the browser engine it is a second capture (see `VoiceGlow`); with the
  // server engine it is the one being recorded.
  const mic = useMicrophone(engine === "server" ? DICTATION_CONSTRAINTS : undefined);
  const send = useMemo<DictationSend | null>(
    () =>
      agentId === null
        ? null
        : (recording, seconds, signal, onProgress) =>
            dictate(agentId, recording, seconds, signal, onProgress),
    [agentId],
  );
  const { state, actions } = useDictation({
    mic,
    send,
    maxSeconds,
    format: status?.format ?? "wav",
  });
  // The agent left `server` mid-dictation: the composer draws the browser's
  // microphone now, and a recording with no Stop button would run on to the
  // limit unseen, so it goes.
  const phase = state.phase;
  const cancel = actions.cancel;
  useEffect(() => {
    if (engine !== "server" && phase !== "idle") cancel();
  }, [engine, phase, cancel]);
  return { status, failed, engine, mic, maxSeconds, state, actions };
}
