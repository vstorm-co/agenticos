"use client";

import { readChatControlPreferences, saveChatControlPreferences } from "./chat-controls-store";
import { create } from "zustand";
import { persist } from "zustand/middleware";
import { useAuthStore } from "./auth-store";
import { useOrgStore } from "./org-store";

import type { LocalAgent, LocalTarget, SkillSource } from "@/lib/desktop/commands";

export type { LocalTarget };

export interface CodingPreferences {
  model: string | null;
  effort: string | null;
}

const DEFAULT_CODING_PREFERENCES: CodingPreferences = { model: null, effort: null };

/**
 * Where each conversation's runs work: the agent's cloud sandbox, or a folder on
 * this computer (#2305).
 *
 * Remembered per conversation, so reopening a chat that worked in a project
 * folder keeps working there. New chats inherit account and organization defaults.
 * `draft` is the choice made before a new chat has an id; it moves under that id when the
 * server files the conversation. Only paths and modes are kept - what the person
 * granted is the desktop app's to check on every operation, not this store's.
 */
const browserKey = (conversationId: string) =>
  `${useAuthStore.getState().user?.id ?? "-"}:${useOrgStore.getState().activeOrgId ?? "-"}:${conversationId}`;

interface WorkOnState {
  /** Private folder mappings never leave this browser's account/organization scope. */
  fileRoots: Record<string, string>;
  rememberFileRoot: (id: string, root: string) => void;
  fileRootFor: (id: string) => string | undefined;
  codingByConversation: Record<string, LocalAgent["id"] | null>;
  draftCoding: LocalAgent["id"] | null;
  codingFor: (conversationId: string | null) => LocalAgent["id"] | null;
  setCoding: (conversationId: string | null, harness: LocalAgent["id"] | null) => void;
  codingPreferencesByConversation: Record<string, CodingPreferences>;
  draftCodingPreferences: CodingPreferences;
  codingPreferencesFor: (conversationId: string | null) => CodingPreferences;
  setCodingPreferences: (conversationId: string | null, preferences: CodingPreferences) => void;
  computerByConversation: Record<string, boolean>;
  draftComputer: boolean | undefined;
  computerFor: (conversationId: string | null) => boolean;
  setComputer: (conversationId: string | null, local: boolean) => void;
  browserByConversation: Record<string, boolean>;
  draftBrowser: boolean | undefined;
  browserFor: (conversationId: string | null) => boolean;
  setBrowser: (conversationId: string | null, local: boolean) => void;
  /**
   * The skill sources a conversation reads from this computer. Off for a new chat:
   * unlike a folder, this is never inherited, so each chat is asked for once.
   */
  skillsByConversation: Record<string, SkillSource[]>;
  draftSkills: SkillSource[];
  skillsFor: (conversationId: string | null) => SkillSource[];
  setSkills: (conversationId: string | null, sources: SkillSource[]) => void;
  /**
   * Where each agent that works on this computer was last allowed to work, so a new
   * chat with it starts there instead of asking again. Its whole-computer consent
   * is the agent's own in the app, not one conversation's.
   */
  agentTargets: Record<string, LocalTarget>;
  agentTargetFor: (agentId: string) => LocalTarget | null;
  rememberForAgent: (agentId: string, target: LocalTarget | null) => void;
  byConversation: Record<string, LocalTarget | null>;
  draft: LocalTarget | null;
  draftProjectKey: string | null;
  /** Apply a project default once; subsequent edits belong to this draft. */
  applyProject: (key: string | null, target: LocalTarget | null) => void;
  resetDraft: () => void;
  /** The target for a conversation, or the draft for one not filed yet. */
  targetFor: (conversationId: string | null) => LocalTarget | null;
  explicitTargetFor: (conversationId: string | null) => LocalTarget | null;
  forgetFolder: (folder: string) => void;
  set: (
    conversationId: string | null,
    target: LocalTarget | null,
    rememberDefault?: boolean,
  ) => void;
  /** File the draft under the id the server just gave the new chat. */
  adopt: (conversationId: string) => void;
}

/** One array for "none", so a selector that reads it returns the same reference every time. */
const NO_SKILLS: SkillSource[] = [];

export const useWorkOnStore = create<WorkOnState>()(
  persist(
    (set, get) => ({
      fileRoots: {},
      rememberFileRoot: (id, root) =>
        set({ fileRoots: { ...get().fileRoots, [browserKey(`file:${id}`)]: root } }),
      fileRootFor: (id) => get().fileRoots[browserKey(`file:${id}`)],
      codingByConversation: {},
      draftCoding: null,
      codingPreferencesByConversation: {},
      draftCodingPreferences: DEFAULT_CODING_PREFERENCES,
      codingPreferencesFor: (conversationId) =>
        conversationId === null
          ? get().draftCodingPreferences
          : (get().codingPreferencesByConversation[browserKey(conversationId)] ??
            DEFAULT_CODING_PREFERENCES),
      setCodingPreferences: (conversationId, preferences) => {
        if (conversationId === null) set({ draftCodingPreferences: preferences });
        else
          set({
            codingPreferencesByConversation: {
              ...get().codingPreferencesByConversation,
              [browserKey(conversationId)]: preferences,
            },
          });
      },
      codingFor: (conversationId) =>
        conversationId === null
          ? get().draftCoding
          : (get().codingByConversation[browserKey(conversationId)] ?? null),
      setCoding: (conversationId, harness) => {
        if (get().codingFor(conversationId) !== harness)
          get().setCodingPreferences(conversationId, DEFAULT_CODING_PREFERENCES);
        if (conversationId === null) set({ draftCoding: harness });
        else
          set({
            codingByConversation: {
              ...get().codingByConversation,
              [browserKey(conversationId)]: harness,
            },
          });
      },
      computerByConversation: {},
      draftComputer: undefined,
      computerFor: (conversationId) =>
        (conversationId === null
          ? get().draftComputer
          : get().computerByConversation[browserKey(conversationId)]) ??
        get().targetFor(conversationId)?.computer ??
        readChatControlPreferences().computer,
      setComputer: (conversationId, local) => {
        saveChatControlPreferences({ computer: local });
        const target = get().targetFor(conversationId);
        if (target !== null) get().set(conversationId, { ...target, computer: local });
        if (conversationId === null) set({ draftComputer: local });
        else
          set({
            computerByConversation: {
              ...get().computerByConversation,
              [browserKey(conversationId)]: local,
            },
          });
      },
      browserByConversation: {},
      draftBrowser: undefined,
      browserFor: (conversationId) =>
        (conversationId === null
          ? get().draftBrowser
          : get().browserByConversation[browserKey(conversationId)]) ??
        get().targetFor(conversationId)?.browser ??
        readChatControlPreferences().browser,
      setBrowser: (conversationId, local) => {
        saveChatControlPreferences({ browser: local });
        const target = get().targetFor(conversationId);
        if (target !== null) get().set(conversationId, { ...target, browser: local });
        if (conversationId === null) set({ draftBrowser: local });
        else
          set({
            browserByConversation: {
              ...get().browserByConversation,
              [browserKey(conversationId)]: local,
            },
          });
      },
      skillsByConversation: {},
      draftSkills: NO_SKILLS,
      skillsFor: (conversationId) =>
        conversationId === null
          ? get().draftSkills
          : (get().skillsByConversation[browserKey(conversationId)] ?? NO_SKILLS),
      setSkills: (conversationId, sources) => {
        if (conversationId === null) set({ draftSkills: sources });
        else
          set({
            skillsByConversation: {
              ...get().skillsByConversation,
              [browserKey(conversationId)]: sources,
            },
          });
      },
      agentTargets: {},
      agentTargetFor: (agentId) => get().agentTargets[browserKey(`agent:${agentId}`)] ?? null,
      rememberForAgent: (agentId, target) => {
        const key = browserKey(`agent:${agentId}`);
        const { [key]: _previous, ...rest } = get().agentTargets;
        set({ agentTargets: target === null ? rest : { ...rest, [key]: target } });
      },
      byConversation: {},
      draft: null,
      draftProjectKey: null,
      applyProject: (key, target) => {
        if (key !== get().draftProjectKey) set({ draftProjectKey: key, draft: target });
      },
      resetDraft: () =>
        set({
          draft: null,
          draftProjectKey: null,
          draftBrowser: undefined,
          draftComputer: undefined,
          draftSkills: NO_SKILLS,
          draftCoding: null,
          draftCodingPreferences: DEFAULT_CODING_PREFERENCES,
        }),
      targetFor: (conversationId) => {
        if (conversationId === null)
          return get().draftProjectKey !== null
            ? get().draft
            : (get().draft ?? readChatControlPreferences().localTarget);
        return Object.hasOwn(get().byConversation, conversationId)
          ? (get().byConversation[conversationId] ?? null)
          : readChatControlPreferences().localTarget;
      },
      explicitTargetFor: (conversationId) =>
        conversationId === null ? get().draft : (get().byConversation[conversationId] ?? null),
      forgetFolder: (folder) => {
        const matches = (target: LocalTarget | null) =>
          target?.folder === folder && !target.computer_grant;
        set({
          agentTargets: Object.fromEntries(
            Object.entries(get().agentTargets).filter(([, target]) => !matches(target)),
          ),
          byConversation: Object.fromEntries(
            Object.entries(get().byConversation).map(([id, target]) => [
              id,
              matches(target) ? null : target,
            ]),
          ),
          draft: matches(get().draft) ? null : get().draft,
        });
        if (matches(readChatControlPreferences().localTarget))
          saveChatControlPreferences({ localTarget: null });
      },
      set: (conversationId, target, rememberDefault = true) => {
        // Whole-computer consent belongs to one conversation and is never inherited.
        if (rememberDefault)
          saveChatControlPreferences({ localTarget: target?.computer_grant ? null : target });
        if (conversationId === null) {
          set({ draft: target });
          return;
        }
        set({ byConversation: { ...get().byConversation, [conversationId]: target } });
      },
      adopt: (conversationId) => {
        const state = get();
        if (Object.hasOwn(state.byConversation, conversationId)) return;
        const key = browserKey(conversationId);
        const target = state.targetFor(null);
        set({
          draft: null,
          draftProjectKey: null,
          draftComputer: undefined,
          draftBrowser: undefined,
          draftSkills: NO_SKILLS,
          skillsByConversation:
            state.draftSkills.length > 0
              ? { ...state.skillsByConversation, [key]: state.draftSkills }
              : state.skillsByConversation,
          codingByConversation: Object.hasOwn(state.codingByConversation, key)
            ? state.codingByConversation
            : { ...state.codingByConversation, [key]: state.codingFor(null) },
          codingPreferencesByConversation: Object.hasOwn(state.codingPreferencesByConversation, key)
            ? state.codingPreferencesByConversation
            : { ...state.codingPreferencesByConversation, [key]: state.codingPreferencesFor(null) },
          draftCoding: null,
          draftCodingPreferences: DEFAULT_CODING_PREFERENCES,
          browserByConversation: Object.hasOwn(state.browserByConversation, key)
            ? state.browserByConversation
            : { ...state.browserByConversation, [key]: state.browserFor(null) },
          computerByConversation: Object.hasOwn(state.computerByConversation, key)
            ? state.computerByConversation
            : { ...state.computerByConversation, [key]: state.computerFor(null) },
          byConversation: { ...state.byConversation, [conversationId]: target },
        });
      },
    }),
    {
      name: "work-on",
      version: 1,
      partialize: ({
        agentTargets,
        fileRoots,
        byConversation,
        browserByConversation,
        computerByConversation,
        skillsByConversation,
        codingByConversation,
        codingPreferencesByConversation,
      }) => ({
        agentTargets,
        fileRoots,
        skillsByConversation,
        codingByConversation,
        codingPreferencesByConversation,
        byConversation,
        browserByConversation,
        computerByConversation,
      }),
    },
  ),
);
