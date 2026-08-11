"use client";

import { useCallback, useMemo, useState } from "react";

import { useAgents } from "@/hooks/use-agents";
import { useKnowledgeBases } from "@/hooks/use-knowledge-bases";
import { useModelProviders } from "@/hooks/use-model-providers";
import { useOrgMcpConnections } from "@/hooks/use-org-mcp-connections";
import { useOrganizationList } from "@/hooks/use-organizations";
import { usePermissions } from "@/hooks/use-permissions";
import { useSkills } from "@/hooks/use-skills";
import {
  FLOWS,
  stepsForFlow,
  type FlowId,
  type FlowResource,
  type FlowStep,
  type OrgState,
} from "@/lib/onboarding/flows";
import { useOnboardingStore } from "@/stores";

export interface OnboardingFlowState {
  /** A flow is running and has at least one step this caller can act on. */
  isActive: boolean;
  flowId: FlowId | null;
  steps: readonly FlowStep[];
  /** The step showing — `steps[index]`, already clamped into range. */
  step: FlowStep | undefined;
  index: number;
  isLast: boolean;
  /**
   * The current step's success event has happened — the reader created the
   * thing, so the coach may advance. `false` for a step with no signal (advance
   * is a Next click) and until the resource's list grows past what it held when
   * the step began.
   */
  signalMet: boolean;
  /** Advance to the next step, or end the flow if this was the last. */
  next: () => void;
  /** End the flow now — the coach's close button. */
  finish: () => void;
}

/** A resource count, or `null` while its list is still loading. */
type MaybeCount = number | null;

/** The org state assumed until the real one has loaded — treat nothing as present. */
const DEFAULT_STATE: OrgState = { hasRunnableModel: false };

/** A list's count, or `null` while it is still loading — the one gate every resource passes through. */
function settled(loading: boolean, count: number): MaybeCount {
  return loading ? null : count;
}

/**
 * The organization snapshot a flow reads: the count of each creatable resource,
 * and the state its adaptive steps branch on. `liveState` is `null` until the
 * model list has loaded, so a flow does not freeze "no runnable model" from the
 * empty first frame.
 *
 * The `null`-while-loading on the counts is load-bearing too: the baseline a step
 * captures must be the real pre-creation count, not the `0` a list reads as before
 * it settles — otherwise a section that already holds three of something would
 * read as "just created one" the moment its list arrived. Every list runs only
 * while a flow is live, because the coach that calls this hook is mounted only
 * then.
 */
function useOrgSnapshot(): {
  counts: Record<FlowResource, MaybeCount>;
  liveState: OrgState | null;
} {
  const agents = useAgents();
  const models = useModelProviders();
  const skills = useSkills();
  const kb = useKnowledgeBases();
  const mcp = useOrgMcpConnections();
  const orgs = useOrganizationList();
  return {
    counts: {
      agent: settled(agents.isLoading, agents.total),
      model: settled(models.isLoading, models.profiles.length),
      skill: settled(skills.isLoading, skills.total),
      kb: settled(kb.isLoading, kb.kbs.length),
      orgMcp: settled(mcp.isLoading, mcp.connections.length),
      org: settled(orgs.isLoading, orgs.data?.length ?? 0),
    },
    // A profile is runnable when it is keyed by a vault secret, or self-hosted at
    // a `base_url` with no key — the same rule the model resolver enforces. A key
    // stored with no profile, or a profile whose key was deleted, is not.
    liveState: models.isLoading
      ? null
      : {
          hasRunnableModel: models.profiles.some(
            (profile) => profile.secret_id !== null || !!profile.base_url,
          ),
        },
  };
}

/**
 * Drives an interactive creation flow: which steps this caller runs, where it
 * has reached, and whether the current step's resource has been created.
 *
 * The state half of the Phase-2 coach, the counterpart to `useOnboardingTour`
 * for the passive tour. It owns the adaptive, permission-filtered step list and
 * the index; the coach in `components/onboarding` reads `step` and `signalMet`
 * from here and does the DOM. Split so keeps this hook inside the 100% gate that
 * `src/hooks/**` carries — the driver-less overlay work that could not meet it
 * lives in the component.
 *
 * A step advances when its resource appears. The count of that resource is
 * captured as the step begins and compared on every render; when the list grows
 * past the baseline the reader has made the thing, and `signalMet` turns true.
 * The comparison is `>`, so it is idempotent under the double cache write the
 * create hooks do (an optimistic patch, then an invalidation). The baseline is
 * captured in state during render rather than in an effect: an effect would miss
 * the first frame, and a list that loads from `0` to its real count would trip
 * the signal before anything was created.
 */
export function useOnboardingFlow(): OnboardingFlowState {
  const isOpen = useOnboardingStore((state) => state.isOpen);
  const mode = useOnboardingStore((state) => state.mode);
  const flowId = useOnboardingStore((state) => state.flowId);
  const index = useOnboardingStore((state) => state.index);
  const setIndex = useOnboardingStore((state) => state.setIndex);
  const close = useOnboardingStore((state) => state.close);
  const { can } = usePermissions();
  const { counts, liveState } = useOrgSnapshot();

  // Freeze the org state at flow start, once its inputs have settled, so an
  // adaptive step does not morph as the reader satisfies it: the "add a model"
  // step must stay "add a model" long enough for the model appearing to advance
  // it, not turn into "pick a model" the instant the profile is created and leave
  // the reader on a step with no signal. Frozen per flow, and the hook remounts
  // between flows, so a reopened flow reads the state afresh.
  const [frozen, setFrozen] = useState<{ flowId: FlowId; state: OrgState } | null>(null);
  if (flowId && liveState && frozen?.flowId !== flowId) {
    setFrozen({ flowId, state: liveState });
  }
  const orgState = frozen?.flowId === flowId ? frozen.state : DEFAULT_STATE;

  const flow = mode === "flow" && flowId ? FLOWS[flowId] : null;
  const steps = useMemo(
    () => (flow ? stepsForFlow(flow, orgState, can) : []),
    [flow, orgState, can],
  );
  const clamped = Math.min(index, Math.max(steps.length - 1, 0));
  const step = steps[clamped];
  const isLast = clamped === steps.length - 1;

  const resource = step?.signal?.resource ?? null;
  const count = resource ? counts[resource] : null;

  // Capture the count as the step began and compare on every render; when the
  // list grows past that baseline the reader has created the thing. State rather
  // than a ref, and adjusted during render (React's supported pattern, the same
  // one `useOnboardingTour` uses for its page anchor): the guard fires the
  // capture at most once per step, so there is no loop, and reading a ref during
  // render is both discouraged and would miss the re-render the new baseline
  // needs. `null` while a list loads holds the baseline until the real count is
  // known, so a list settling from 0 to its true size does not read as a
  // creation.
  const stepKey = `${flowId}:${clamped}`;
  const [baseline, setBaseline] = useState<{ key: string; count: number } | null>(null);
  if (resource !== null && count !== null && baseline?.key !== stepKey) {
    setBaseline({ key: stepKey, count });
  }
  const signalMet =
    resource !== null && count !== null && baseline?.key === stepKey && count > baseline.count;

  const next = useCallback(() => {
    if (clamped >= steps.length - 1) close();
    else setIndex(clamped + 1);
  }, [clamped, steps.length, setIndex, close]);

  const finish = useCallback(() => close(), [close]);

  return {
    isActive: isOpen && flow !== null && steps.length > 0,
    flowId: flow ? flowId : null,
    steps,
    step,
    index: clamped,
    isLast,
    signalMet,
    next,
    finish,
  };
}
