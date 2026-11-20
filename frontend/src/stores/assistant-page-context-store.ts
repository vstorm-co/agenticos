"use client";

import { create } from "zustand";

import type { AssistantPageDetails } from "@/lib/assistant-page-context";

interface PageRegistration {
  owner: string;
  scope: string;
  path: string;
  details: AssistantPageDetails;
}

interface AssistantPageContextState {
  registrations: PageRegistration[];
  register: (registration: PageRegistration) => void;
  remove: (owner: string) => void;
}

/** Mounted page details only. No browser storage and no transcript persistence. */
export const useAssistantPageContextStore = create<AssistantPageContextState>((set) => ({
  registrations: [],
  register: (registration) =>
    set((state) => ({
      registrations: [
        ...state.registrations.filter((entry) => entry.owner !== registration.owner),
        registration,
      ],
    })),
  remove: (owner) =>
    set((state) => ({
      registrations: state.registrations.filter((entry) => entry.owner !== owner),
    })),
}));
