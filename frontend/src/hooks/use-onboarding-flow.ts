"use client";

import { useCallback, useMemo, useState } from "react";
import { usePathname } from "next/navigation";

import { useAgent, useAgents } from "@/hooks/use-agents";
import { useCanCreateTriggerQuery } from "@/hooks/use-can-create-trigger";
import { useKnowledgeBases } from "@/hooks/use-knowledge-bases";
import { useMcpConnections } from "@/hooks/use-mcp-connections";
import { useModelProviders } from "@/hooks/use-model-providers";
import { useOrgMcpConnections } from "@/hooks/use-org-mcp-connections";
import { useOrgTriggers } from "@/hooks/use-org-triggers";
import { useOrganizationList } from "@/hooks/use-organizations";
import { usePermissions } from "@/hooks/use-permissions";
import { useSkills } from "@/hooks/use-skills";
import { stripLocale } from "@/lib/active-route";
import {
  FLOWS,
  stepsForFlow,
  type FlowId,
  type FlowResource,
  type FlowStep,
  type OrgState,
} from "@/lib/onboarding/flows";
import { pageKey } from "@/lib/onboarding/tour";
import { useOnboardingStore } from "@/stores";
import { useAgentSelectionStore } from "@/stores/agent-selection-store";
import { useChatStore } from "@/stores/chat-store";
import type { ChoiceValue } from "@/stores/onboarding-store";

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
   * The current step's success event has happened, so the coach may advance: the
   * reader created the resource a `created` step names, or reached the page an
   * `arrived` step names. `false` for a step with no signal (advance is a Next
   * click), and until that event.
   */
  signalMet: boolean;
  /** Advance to the next step, or end the flow if this was the last. */
  next: () => void;
  /** End the flow now — the coach's close button. */
  finish: () => void;
  /**
   * Answer a fork step: records the choice and steps onto whatever it opens, or
   * ends the walk when the choice opens nothing and the fork was the last step.
   */
  answer: (questionId: string, value: ChoiceValue) => void;
  /** Hand off to another flow — a fork whose `"yes"` starts a different one. */
  openFlow: (flowId: FlowId) => void;
  /** The agent this flow created, for a detour's return leg; `null` until captured. */
  flowAgentId: string | null;
  /** Remember the agent the flow just created — the coach reads it from the builder URL. */
  setFlowAgentId: (agentId: string) => void;
}

/** A resource count, or `null` while its list is still loading. */
type MaybeCount = number | null;

/** The org state assumed until the real one has loaded — treat nothing as present. */
const DEFAULT_STATE: OrgState = {
  hasRunnableModel: false,
  hasKnowledgeBase: false,
  hasSkill: false,
  hasOrgMcp: false,
  hasPublishedAgent: false,
  hasRunnableAgent: false,
};

/**
 * A list's count, or `null` while it is still in flight — the one gate every
 * resource passes through.
 *
 * `fetching`, not only `loading`: React Query reports `isLoading` false the moment
 * it has *cached* data, while a background refresh of that cache is still running.
 * A step that baselined on the cached number then read the refresh alone as a
 * creation — a colleague's row, or one made in another tab since the cache was
 * filled, advancing the step with nothing done here.
 */
function settled(loading: boolean, fetching: boolean, count: number): MaybeCount {
  return loading || fetching ? null : count;
}

/**
 * The organization snapshot a flow reads: the count of each creatable resource,
 * and the state its adaptive steps branch on. `liveState` is `null` until the
 * lists it reads have loaded, so a flow does not freeze "no runnable model" or
 * "no knowledge base" from the empty first frame and offer to create what is
 * merely not yet fetched.
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
  const personalMcp = useMcpConnections();
  const orgs = useOrganizationList();
  // The org-wide list, which is what the Routines page shows and therefore what
  // grows by one when the reader creates a schedule or a trigger.
  const routines = useOrgTriggers();
  // The same query the Routines page gates its create buttons on
  // (`qk.agents.anyRunnable()`), so the flow and the buttons can never disagree.
  // `isFetching` too, not only `isLoading`: a cached answer being refetched is a
  // stale one, and freezing it can strand the flow either way - a revoked grant
  // waits on buttons the refresh hides, a fresh grant reads as inert.
  const anyRunnable = useCanCreateTriggerQuery();
  const stateSettled =
    !agents.isLoading &&
    !models.isLoading &&
    !kb.isLoading &&
    !skills.isLoading &&
    !mcp.isLoading &&
    !personalMcp.isLoading &&
    !anyRunnable.isLoading &&
    !anyRunnable.isFetching;
  return {
    counts: {
      agent: settled(agents.isLoading, agents.isFetching, agents.total),
      model: settled(models.isLoading, models.isFetching, models.profiles.length),
      skill: settled(skills.isLoading, skills.isFetching, skills.total),
      kb: settled(kb.isLoading, kb.isFetching, kb.kbs.length),
      // Either scope: the connect step ends when the reader connects one, org or
      // personal. `hasOrgMcp` below stays org-only — that is the fork for an agent
      // binding a server, and an agent binds the organization's.
      mcp: settled(
        mcp.isLoading || personalMcp.isLoading,
        mcp.isFetching || personalMcp.isFetching,
        mcp.connections.length + personalMcp.connections.length,
      ),
      org: settled(orgs.isLoading, orgs.isFetching, orgs.data?.length ?? 0),
      routine: settled(routines.isLoading, false, routines.total),
    },
    // A profile is runnable when it is keyed by a vault secret, or self-hosted at
    // a `base_url` with no key — the same rule the model resolver enforces. A key
    // stored with no profile, or a profile whose key was deleted, is not. The
    // knowledge, skill and MCP flags are simply whether the organization holds one,
    // the fork each section's step branches on. A published agent is the one the
    // chat can address — a draft has no version to run — the same `status` check
    // the chat's own picker makes.
    liveState: stateSettled
      ? {
          hasRunnableModel: models.profiles.some(
            (profile) => profile.secret_id !== null || !!profile.base_url,
          ),
          hasKnowledgeBase: kb.kbs.length > 0,
          hasSkill: skills.total > 0,
          hasOrgMcp: mcp.connections.length > 0,
          hasPublishedAgent: agents.agents.some((agent) => agent.status === "published"),
          hasRunnableAgent: anyRunnable.canCreate,
        }
      : null,
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
 *
 * A fork's answer is resolved here rather than in the store, and this is why: the
 * store advances by an index it is handed, because where an answer lands depends on
 * the list the answer produces and the store cannot see that list. A fork *can* be a
 * flow's last surviving step — create-agent's tail is gated on `agents:publish`, so
 * a role holding `agents:edit` and `collections:edit` and nothing else walks a flow
 * ending on the "add a knowledge base?" question — and a Skip there widens nothing.
 * Stepping past it blindly put the reader back on the question they had just
 * answered, with Skip re-answering it forever and the close button the only way out.
 * So a choice that opens nothing after the last step ends the walk, decided before
 * the update rather than clamped after it, and no frame shows the answered question
 * again.
 */
export function useOnboardingFlow(): OnboardingFlowState {
  const isOpen = useOnboardingStore((state) => state.isOpen);
  const mode = useOnboardingStore((state) => state.mode);
  const flowId = useOnboardingStore((state) => state.flowId);
  const index = useOnboardingStore((state) => state.index);
  const setIndex = useOnboardingStore((state) => state.setIndex);
  const close = useOnboardingStore((state) => state.close);
  const choices = useOnboardingStore((state) => state.choices);
  const recordAnswer = useOnboardingStore((state) => state.answer);
  const openFlow = useOnboardingStore((state) => state.openFlow);
  const flowAgentId = useOnboardingStore((state) => state.flowAgentId);
  const setFlowAgentId = useOnboardingStore((state) => state.setFlowAgentId);
  const { can } = usePermissions();
  const { counts, liveState } = useOrgSnapshot();
  // The live draft of the agent this flow built, for the steps that gate on its
  // state rather than a list: the model step waits for its draft to gain a model,
  // the publish step for it to gain a published version. Disabled until an id is
  // captured (`flowAgentId` null), and it shares the builder's own query key, so
  // the builder's autosave and publish invalidations refresh it here too.
  const agentDetail = useAgent(flowAgentId);
  const here = pageKey(stripLocale(usePathname()));
  // The chat run's tail keys off the chat stores rather than a list: which agent
  // is selected, and how many messages are *on screen* — sending appends one
  // optimistically, so the count growing is the send. Read here so `signalMet` can
  // settle a `selected`/`sent` step.
  //
  // The on-screen transcript (`useChatStore`), not the fetched one: a send appends
  // there and nowhere else, and `useConversationStore.currentMessages` holds only
  // what a fetch returned — which for a conversation created over the websocket is
  // never fetched at all and stays empty however many turns it holds. Read from
  // there, the fresh-agent path's first message never moved the count and the coach
  // sat on the composer while the run it asked for was already answering.
  const selectedAgentId = useAgentSelectionStore((state) => state.selectedAgentId);
  const messageCount = useChatStore((state) => state.messages.length);

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
  // The snapshot is ready only once it is frozen for *this* flow. Until then the
  // steps below are computed from DEFAULT_STATE ("the org has nothing"), so
  // activating the coach on them would flash a fork built for an empty org — "no
  // published agent, build one?" over an org that has one — and swap it away the
  // moment the lists settle. `isActive` waits for `stateReady`, so the coach
  // renders nothing until the state it will freeze on has landed.
  const stateReady = frozen?.flowId === flowId;
  const orgState = frozen?.flowId === flowId ? frozen.state : DEFAULT_STATE;

  const flow = mode === "flow" && flowId ? FLOWS[flowId] : null;
  const steps = useMemo(
    () => (flow ? stepsForFlow(flow, orgState, can, choices) : []),
    [flow, orgState, can, choices],
  );
  const clamped = Math.min(index, Math.max(steps.length - 1, 0));
  const step = steps[clamped];
  const isLast = clamped === steps.length - 1;

  const signal = step?.signal;
  const resource = signal?.kind === "created" ? signal.resource : null;
  // A `sent` step baselines the on-screen transcript the same way a `created` step
  // baselines its list: the send is the count growing while the step shows. Keyed
  // to the step, so a message sent in an earlier session never reads as this send —
  // and the freeze keeps the sidebar out of reach, so nothing else can grow it. The
  // step before it clears the open conversation (`freshConversation`), which is
  // what keeps the transcript's own load from reading as the send.
  const count = resource ? counts[resource] : signal?.kind === "sent" ? messageCount : null;
  const needsBaseline = resource !== null || signal?.kind === "sent";

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
  if (needsBaseline && count !== null && baseline?.key !== stepKey) {
    setBaseline({ key: stepKey, count });
  }
  // How each signal settles. `created` and `sent` grow their count past the
  // step's baseline; `arrived` reaches the page it names; `modelSet`, `published`
  // and `selected` read the agent this flow built (`flowAgentId`) — its draft
  // gaining a model, its gaining a published version, and its being the agent the
  // chat will address. Each step carries at most one, so they never contend.
  const signalMet =
    signal?.kind === "arrived"
      ? here === signal.page
      : signal?.kind === "modelSet"
        ? agentDetail.agent?.draft_spec.model_profile_id != null
        : signal?.kind === "published"
          ? agentDetail.agent?.status === "published"
          : signal?.kind === "selected"
            ? flowAgentId !== null && selectedAgentId === flowAgentId
            : needsBaseline &&
              count !== null &&
              baseline?.key === stepKey &&
              count > baseline.count;

  const next = useCallback(() => {
    if (clamped >= steps.length - 1) close();
    else setIndex(clamped + 1);
  }, [clamped, steps.length, setIndex, close]);

  const finish = useCallback(() => close(), [close]);

  const answer = useCallback(
    (questionId: string, value: ChoiceValue) => {
      if (!flow) return;
      const widened = stepsForFlow(flow, orgState, can, { ...choices, [questionId]: value });
      if (clamped >= widened.length - 1) close();
      else recordAnswer(questionId, value, clamped + 1);
    },
    [flow, orgState, can, choices, clamped, close, recordAnswer],
  );

  return {
    isActive: isOpen && flow !== null && stateReady && steps.length > 0,
    flowId: flow ? flowId : null,
    steps,
    step,
    index: clamped,
    isLast,
    signalMet,
    next,
    finish,
    answer,
    openFlow,
    flowAgentId,
    setFlowAgentId,
  };
}
