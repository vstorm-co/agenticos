"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { User } from "@/types";

interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  accessToken: string | null;
  avatarVersion: number;
  /**
   * The account the browser's cached and stored state belongs to.
   *
   * Separate from `user` because `user` goes null for reasons that are not a
   * change of account - a transient `/auth/me` failure nulls it, and treating
   * that as somebody new arriving would throw away the selections of the person
   * who is still signed in. Written only when an account is successfully
   * adopted, and cleared only by a deliberate sign-out.
   */
  sessionOwnerId: string | null;

  setUser: (user: User | null) => void;
  setSessionOwnerId: (id: string | null) => void;
  setLoading: (loading: boolean) => void;
  setAccessToken: (token: string | null) => void;
  checkAuth: () => Promise<void>;
  logout: () => void;
  bumpAvatarVersion: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      isAuthenticated: false,
      isLoading: true,
      accessToken: null,
      avatarVersion: 0,
      sessionOwnerId: null,

      setUser: (user) =>
        set({
          user,
          isAuthenticated: user !== null,
          isLoading: false,
        }),

      setSessionOwnerId: (id) => set({ sessionOwnerId: id }),

      setLoading: (loading) => set({ isLoading: loading }),

      setAccessToken: (token) => set({ accessToken: token }),

      bumpAvatarVersion: () => set((s) => ({ avatarVersion: s.avatarVersion + 1 })),

      checkAuth: async () => {
        try {
          set({ isLoading: true });
          const response = await fetch("/api/auth/me");
          if (response.ok) {
            const user = await response.json();
            set({ user, isAuthenticated: true, isLoading: false });
          } else {
            set({ user: null, isAuthenticated: false, isLoading: false });
          }
        } catch {
          set({ user: null, isAuthenticated: false, isLoading: false });
        }
      },

      logout: () =>
        set({
          user: null,
          isAuthenticated: false,
          isLoading: false,
          accessToken: null,
          sessionOwnerId: null,
        }),
    }),
    {
      name: "auth-storage",
      partialize: (state) => ({
        user: state.user,
        isAuthenticated: state.isAuthenticated,
        sessionOwnerId: state.sessionOwnerId,
        // Note: accessToken is intentionally NOT persisted - kept in-memory only
      }),
    },
  ),
);
