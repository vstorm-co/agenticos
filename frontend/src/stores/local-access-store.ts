"use client";

import { create } from "zustand";

import type { LocalTarget } from "@/lib/desktop/commands";

/** The agent a chat is about to send to, as the question about its access names it. */
export interface LocalAccessAgent {
  id: string;
  name: string;
  /** Its coding agent runs as the person, so only full access can host it. */
  coding: boolean;
  /** What the requesting turn needs the computer for. */
  reason?: string;
}

interface LocalAccessState {
  /** The agent being asked about, or null when nothing is asked. */
  asking: LocalAccessAgent | null;
  resolve: ((target: LocalTarget | null) => void) | null;
  /**
   * Ask where an agent that works on this computer may work.
   *
   * Resolves with the chosen target, or null when the person declines. A second
   * question while one is open settles the first as declined: one dialog at a time.
   */
  request: (agent: LocalAccessAgent) => Promise<LocalTarget | null>;
  answer: (target: LocalTarget | null) => void;
}

export const useLocalAccessStore = create<LocalAccessState>()((set, get) => ({
  asking: null,
  resolve: null,
  request: (agent) => {
    get().resolve?.(null);
    return new Promise((resolve) => set({ asking: agent, resolve }));
  },
  answer: (target) => {
    get().resolve?.(target);
    set({ asking: null, resolve: null });
  },
}));
