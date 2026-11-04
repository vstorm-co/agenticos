"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { ApiError, apiClient } from "@/lib/api-client";
import { getErrorMessage } from "@/lib/api-error";
import {
  consolePath,
  inputProblems,
  progress,
  rejection,
  resolveAction,
  runRequestFrom,
  sameRun,
  settledRun,
  startedRun,
  type InputProblem,
  type RejectReason,
  type RunRequest,
} from "@/lib/artifact-actions";
import { qk } from "@/lib/query-keys";
import type {
  ArtifactActionRun,
  ArtifactActionRunStarted,
  ArtifactActionView,
} from "@/types/artifact";

/** Who the console is asking right now: one confirmation at a time, of either kind. */
export type Asking = "link" | "run" | null;

/** The gate link and run dialogs share, so a page cannot stack one question on another. */
export interface AskingGate {
  /** What is being asked right now, if anything. */
  held: () => Asking;
  /** Takes the gate for `kind`; false, and nothing changes, when it is held. */
  take: (kind: "link" | "run") => boolean;
  /** Lets go, only if `kind` is what holds it. */
  release: (kind: "link" | "run") => void;
}

/** One gate for the life of the component that owns both dialogs. */
export function useAskingGate(): AskingGate {
  const [gate] = useState<AskingGate>(() => {
    let held: Asking = null;
    return {
      held: () => held,
      take: (kind) => {
        if (held !== null) return false;
        held = kind;
        return true;
      },
      release: (kind) => {
        if (held === kind) held = null;
      },
    };
  });
  return gate;
}

/** How many times a person may decline for one served page (nonce and version) before it is not asked again. */
export const MAX_CANCELS = 3;

/** The first wait before reading a run again, and the longest one. */
const FIRST_POLL_MS = 500;
const LONGEST_POLL_MS = 5000;
const POLL_BACKOFF = 1.5;
/** Reads that failed in a row before the run is given up on, for the page. */
const MAX_FAILED_READS = 3;
/** How long a paused run is read for, in time spent waiting with the tab visible. */
export const PAUSED_POLL_LIMIT_MS = 10 * 60 * 1000;

/** Resolves when the tab is visible: at once if it already is. */
function whenVisible(): Promise<void> {
  if (!document.hidden) return Promise.resolve();
  return new Promise((resolve) => {
    const onChange = () => {
      if (document.hidden) return;
      document.removeEventListener("visibilitychange", onChange);
      resolve();
    };
    document.addEventListener("visibilitychange", onChange);
  });
}

/** The requests the console makes of the server for a page's actions. */
export function useArtifactActionApi(artifactId: string) {
  const queryClient = useQueryClient();
  return useMemo(
    () => ({
      start: (versionId: string, workflowId: string, input: Record<string, unknown>) =>
        apiClient.post<ArtifactActionRunStarted>(
          `/apps/${artifactId}/versions/${versionId}/actions/${workflowId}/runs`,
          { input },
        ),
      // Never served from the cache: a run moves, and every read is the point.
      read: (runId: string) =>
        queryClient.fetchQuery({
          queryKey: qk.artifacts.actionRun(artifactId, runId),
          queryFn: () =>
            apiClient.get<ArtifactActionRun>(`/apps/${artifactId}/actions/runs/${runId}`),
          staleTime: 0,
          gcTime: 0,
          retry: false,
        }),
    }),
    [artifactId, queryClient],
  );
}

/** A request waiting on the person, with what the dialog needs to show it. */
export interface PendingAction {
  request: RunRequest;
  action: ArtifactActionView;
}

/** A run waiting on someone, which the console points at. */
export interface PausedRun {
  runId: string;
  name: string;
  path: string;
}

interface Options {
  artifactId: string;
  frame: React.RefObject<HTMLIFrameElement | null>;
  /** The nonce of this load of the page; a message under any other is not its own. */
  nonce: string;
  /** The version the server served, which a start names - never the page. */
  versionId: string;
  /** The view says this is the page viewer's address. Off, nothing is listened for. */
  enabled: boolean;
  actions: readonly ArtifactActionView[];
  /** Shared with the link dialog: only one of the two may be open. */
  asking: AskingGate;
}

/**
 * The console's half of a page's actions: takes the page's requests, asks the
 * person, starts what they agree to and tells the page how it goes.
 *
 * - One request at a time: the first stays until decided, a later one is
 *   refused as `busy`, so the input the person reads is never swapped for
 *   another just before they click.
 * - One question at a time across the console: while a link is being asked
 *   about (`asking`), a request is refused as `busy`, and the other way round.
 * - Three declines for one served page - one nonce and version, reloads of its
 *   document included - and it is not asked again: further requests are refused
 *   as `too_many_cancels` with no dialog. Only a new nonce or version resets it.
 * - A request before the frame's first load of this nonce is refused as
 *   `not_ready` - and the page's own bridge refuses one made before its document
 *   has loaded, a reload included; one that names no declared action as `unknown_action`; one
 *   that does not fit the action's fields as `invalid_input`, with the
 *   problems. None of these opens a dialog or spends a decline.
 *   The version a start names is `versionId`, from the view.
 * - The dialog and every run being followed end when the frame loads again or
 *   its nonce or served version changes: the page that asked is gone. A load of the
 *   same nonce tells the new document nothing; a changed nonce is answered
 *   `page_changed` under the old one, which no page of the new load reads.
 * - A started run is read with a growing delay until it finishes; each change
 *   is posted to the frame. A paused one is listed in `paused`, and is read
 *   only while the tab is visible and for ten minutes of that: after it the
 *   page's promise settles with the last projection (`paused: true`,
 *   `finished: false`), it hears nothing more, and the listed run is the way
 *   to it. A page that is gone or reloaded is told nothing: ids restart with
 *   each document, so a late event could settle another run.
 *
 * `*` as the target because the page's origin is opaque and cannot be named.
 */
export function useArtifactActions({
  artifactId,
  frame,
  nonce,
  versionId,
  enabled,
  actions,
  asking,
}: Options) {
  const t = useTranslations("artifacts");
  const tErrors = useTranslations("errors");
  const api = useArtifactActionApi(artifactId);
  const [pending, setPending] = useState<PendingAction | null>(null);
  const [paused, setPaused] = useState<PausedRun[]>([]);
  // What a message needs to be decided on at the moment it arrives, kept out of
  // state so two requests in one tick cannot both find the dialog closed.
  const session = useRef({ open: false, cancels: 0, generation: 0, loadedFor: "" });
  const current = useRef({ nonce, versionId, api });
  useEffect(() => {
    current.current = { nonce, versionId, api };
  });

  // One function for the life of the hook: it reads the frame when called, never while rendering.
  const [post] = useState(
    () => (message: object) => frame.current?.contentWindow?.postMessage(message, "*"),
  );

  const pendingRef = useRef<PendingAction | null>(null);
  const ask = useCallback((next: PendingAction | null) => {
    pendingRef.current = next;
    setPending(next);
  }, []);

  /** The run dialog is no longer open, so the gate may be taken by a link. */
  const release = useCallback(() => {
    session.current.open = false;
    asking.release("run");
  }, [asking]);

  /** The page is gone or changed: end the dialog and every follower without a word to a new page. */
  const reset = useCallback(
    (asked: PendingAction | null, at: string) => {
      session.current.generation += 1;
      release();
      if (asked !== null) post(rejection(at, asked.request.id, "page_changed"));
      ask(null);
      setPaused((all) => (all.length === 0 ? all : []));
    },
    [post, ask, release],
  );

  // Another nonce or served version is another page: it is asked three times again,
  // and has not loaded. Also at unmount. A reload of the same page does not reset.
  useEffect(() => {
    const at = nonce;
    session.current.cancels = 0;
    return () => reset(pendingRef.current, at);
  }, [nonce, versionId, reset]);

  const onLoad = useCallback(() => {
    session.current.loadedFor = current.current.nonce;
    // The document that asked is gone, and this one is the same nonce: a rejection
    // posted now would reach a page that asked nothing yet - its first request is `r1`
    // too - so the dialog ends without a word. A page that asks before it has loaded is
    // answered `not_ready` by its own bridge.
    reset(null, current.current.nonce);
  }, [reset]);

  const follow = useCallback(
    async (request: RunRequest, runId: string, name: string, at: string, generation: number) => {
      let delay = FIRST_POLL_MS;
      let failed = 0;
      let last: ArtifactActionRun | null = null;
      let pausedFor = 0;
      const alive = () => session.current.generation === generation;
      while (alive()) {
        if (pausedFor > 0) {
          if (pausedFor >= PAUSED_POLL_LIMIT_MS) {
            // Settle the page's promise with the last projection; the listed run is the way on.
            if (last !== null) post(settledRun(at, request.id, last));
            return;
          }
          await whenVisible();
          if (!alive()) return;
        }
        await new Promise((resolve) => setTimeout(resolve, delay));
        if (!alive()) return;
        const waited = delay;
        delay = Math.min(delay * POLL_BACKOFF, LONGEST_POLL_MS);
        let run: ArtifactActionRun | null = null;
        try {
          run = await current.current.api.read(runId);
        } catch {
          // Counted below, once the page is known to still be there.
        }
        if (!alive()) return;
        if (run === null) {
          failed += 1;
          if (failed >= MAX_FAILED_READS) {
            post(rejection(at, request.id, "failed"));
            return;
          }
          continue;
        }
        failed = 0;
        pausedFor = run.paused ? pausedFor + waited : 0;
        if (!sameRun(last, run)) {
          last = run;
          post(progress(at, request.id, run));
          const path = run.paused ? consolePath(run.run_path) : null;
          setPaused((all) => {
            const rest = all.filter((item) => item.runId !== runId);
            return path === null ? rest : [...rest, { runId, name, path }];
          });
        }
        if (run.finished) return;
      }
    },
    [post],
  );

  const refuse = useCallback(
    (request: RunRequest, reason: RejectReason, at: string, problems?: InputProblem[]) =>
      post(rejection(at, request.id, reason, problems)),
    [post],
  );

  useEffect(() => {
    if (!enabled) return;
    const listen = (event: MessageEvent) => {
      const request = runRequestFrom(event, frame.current, nonce);
      if (request === null) return;
      if (session.current.loadedFor !== nonce) return refuse(request, "not_ready", nonce);
      if (session.current.open || asking.held() !== null) return refuse(request, "busy", nonce);
      if (session.current.cancels >= MAX_CANCELS) return refuse(request, "too_many_cancels", nonce);
      const action = resolveAction(actions, request.action);
      if (action === null) return refuse(request, "unknown_action", nonce);
      const problems = inputProblems(action.fields, request.input);
      if (problems.length > 0) return refuse(request, "invalid_input", nonce, problems);
      session.current.open = true;
      asking.take("run");
      ask({ request, action });
    };
    window.addEventListener("message", listen);
    return () => window.removeEventListener("message", listen);
  }, [enabled, frame, nonce, actions, asking, refuse, ask]);

  const cancel = useCallback(() => {
    const asked = pendingRef.current;
    if (asked === null) return;
    release();
    session.current.cancels += 1;
    ask(null);
    refuse(asked.request, "cancelled", current.current.nonce);
  }, [refuse, ask, release]);

  const confirm = useCallback(async () => {
    const asked = pendingRef.current;
    const { nonce: at, versionId: version } = current.current;
    if (asked === null) return;
    const generation = session.current.generation;
    release();
    ask(null);
    try {
      const started = await current.current.api.start(
        version,
        asked.action.workflow_id,
        asked.request.input,
      );
      if (session.current.generation !== generation) return;
      post(progress(at, asked.request.id, startedRun(started.status)));
      void follow(asked.request, started.run_id, asked.action.name, at, generation);
    } catch (error) {
      if (session.current.generation !== generation) return;
      const status = error instanceof ApiError ? error.status : 0;
      if (status === 429) toast.error(t("actions.rateLimited"));
      else if (status !== 422 && status !== 404) toast.error(getErrorMessage(error, tErrors));
      const reason: RejectReason =
        status === 429
          ? "rate_limited"
          : status === 422
            ? "invalid_input"
            : status === 404
              ? "not_found"
              : status === 409
                ? "unavailable"
                : "failed";
      refuse(asked.request, reason, at);
    }
  }, [follow, post, refuse, ask, release, t, tErrors]);

  return { pending, paused, cancel, confirm, onLoad };
}
