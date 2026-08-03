"use client";

import { useCallback, useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { resetSessionState, useAuthStore } from "@/stores";
import { apiClient, ApiError } from "@/lib/api-client";
import type { User, LoginRequest, RegisterRequest } from "@/types";
import { postSignInDestination } from "@/lib/auth-landing";
import { ROUTES } from "@/lib/constants";

// Session-level singletons so /auth/me runs ONCE per page load no matter how
// many components mount useAuth(). Concurrent mounts share the in-flight
// promise; later mounts skip entirely (the store is persisted across the
// session). Reset on logout so the next login re-checks.
let authCheckPromise: Promise<void> | null = null;
let authChecked = false;

// Access tokens expire after 15 min. The in-memory token (used by the chat
// WebSocket and proxied API calls) is set once on load and would otherwise go
// stale while the tab stays open - causing WS auth failures / "Offline" chat.
// Refresh it ahead of expiry on a single shared interval. /auth/me
// transparently mints a fresh access token from the refresh cookie.
let tokenRefreshTimer: ReturnType<typeof setInterval> | null = null;
const TOKEN_REFRESH_INTERVAL_MS = 10 * 60 * 1000;

function ensureTokenRefresh(adopt: (u: User) => void): void {
  if (tokenRefreshTimer) return;
  tokenRefreshTimer = setInterval(() => {
    if (!useAuthStore.getState().isAuthenticated) return;
    void (async () => {
      try {
        const { access_token, ...userData } = await apiClient.get<User & { access_token?: string }>(
          "/auth/me",
        );
        // The answer says who the cookie belongs to now, and cookies are shared
        // across tabs: signing in as somebody else in another tab used to leave
        // this one rendering the first account while installing the second
        // one's token, so every request it made authenticated as them. The
        // identity was in this response all along and was being dropped.
        adopt(userData as User);
        if (access_token) useAuthStore.getState().setAccessToken(access_token);
      } catch {
        // Ignore - the next real request (or its 401 → refresh) handles failure.
      }
    })();
  }, TOKEN_REFRESH_INTERVAL_MS);
}

function stopTokenRefresh(): void {
  if (tokenRefreshTimer) {
    clearInterval(tokenRefreshTimer);
    tokenRefreshTimer = null;
  }
}

/**
 * Adopt a signed-in identity, emptying whatever the previous one left behind.
 *
 * Keyed on the account rather than on the act of signing in, because signing in
 * is not one act: a password login, an OAuth callback and a magic link all
 * establish a session by different routes, and hanging the cleanup off any one
 * of them leaves the others handing the new account the previous one's data.
 *
 * The comparison is against `sessionOwnerId` rather than against `user`,
 * because `user` goes null for reasons that are not somebody else arriving - a
 * transient `/auth/me` failure is one - and that must not cost the person still
 * signed in their cache, their selected organization or their agent. Reloading
 * a page adopts the same id and likewise changes nothing.
 *
 * Any other id clears, including arriving with no owner recorded. A refused
 * token refresh calls the store's `logout` directly, which leaves no owner and
 * a full cache behind it, so "nobody owns this" is not the same as "there is
 * nothing here". On a browser that really is empty the clear costs nothing.
 */
function adoptUser(
  queryClient: QueryClient,
  setUser: (u: User | null) => void,
  user: User | null,
): void {
  const { sessionOwnerId, setSessionOwnerId } = useAuthStore.getState();
  if (user && sessionOwnerId !== user.id) {
    queryClient.clear();
    resetSessionState();
    setSessionOwnerId(user.id);
  }
  setUser(user);
}

/**
 * Adopt a session established outside `login` - today, the OAuth callback.
 *
 * That page exchanges its code for a user and a token and had been writing both
 * straight into the store, which skipped the cleanup and left the previous
 * account's cache in place. Signing in through Google is still signing in.
 */
export function useAdoptSession(): (user: User, accessToken: string | null) => void {
  const queryClient = useQueryClient();
  const setUser = useAuthStore((state) => state.setUser);
  return useCallback(
    (user: User, accessToken: string | null) => {
      adoptUser(queryClient, setUser, user);
      useAuthStore.getState().setAccessToken(accessToken);
    },
    [queryClient, setUser],
  );
}

/**
 * Re-read who is signed in, adopting whoever answers.
 *
 * For a flow that establishes the session server-side and gets no user back:
 * the magic link answers with tokens only, so there is nothing for
 * `useAdoptSession` to adopt. The auth check otherwise runs once per page load,
 * and a tab that had already asked keeps the account it asked about - so
 * verifying a link for somebody else left the previous account's cache on
 * screen while every request authenticated as the new one.
 *
 * Awaited before the redirect, so the change of account is settled while the
 * page still says "verifying" rather than a frame into the next one.
 */
export function useReauthenticate(): () => Promise<void> {
  const queryClient = useQueryClient();
  const setUser = useAuthStore((state) => state.setUser);
  return useCallback(async () => {
    authChecked = false;
    authCheckPromise = null;
    await runAuthCheck((u) => adoptUser(queryClient, setUser, u));
  }, [queryClient, setUser]);
}

function runAuthCheck(setUser: (u: User | null) => void): Promise<void> {
  if (authChecked) return Promise.resolve();
  if (authCheckPromise) return authCheckPromise;
  authCheckPromise = (async () => {
    try {
      const data = await apiClient.get<User & { access_token?: string }>("/auth/me");
      const { access_token, ...userData } = data;
      setUser(userData as User);
      useAuthStore.getState().setAccessToken(access_token ?? null);
    } catch {
      setUser(null);
      useAuthStore.getState().setAccessToken(null);
    } finally {
      authChecked = true;
      authCheckPromise = null;
    }
  })();
  return authCheckPromise;
}

export function useAuth() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { user, isAuthenticated, isLoading, setUser, setLoading, logout } = useAuthStore();

  // Check auth status once per session. /auth/me returns the access_token in
  // the body (httpOnly cookie isn't JS-readable) for WebSocket auth.
  useEffect(() => {
    const adopt = (u: User | null) => adoptUser(queryClient, setUser, u);
    void runAuthCheck(adopt);
    ensureTokenRefresh(adopt);
  }, [setUser, queryClient]);

  const login = useCallback(
    async (credentials: LoginRequest, returnTo?: string | null) => {
      setLoading(true);
      try {
        const response = await apiClient.post<{
          user: User;
          access_token: string;
          message: string;
        }>("/auth/login", credentials);
        adoptUser(queryClient, setUser, response.user);
        useAuthStore.getState().setAccessToken(response.access_token);
        authChecked = true; // login already populated user + token; skip /auth/me
        router.push(postSignInDestination(returnTo));
        return response;
      } finally {
        setLoading(false);
      }
    },
    [router, setUser, setLoading, queryClient],
  );

  const register = useCallback(async (data: RegisterRequest) => {
    const response = await apiClient.post<{ id: string; email: string }>("/auth/register", data);
    return response;
  }, []);

  const handleLogout = useCallback(async () => {
    try {
      await apiClient.post("/auth/logout");
    } catch {
      // Ignore logout errors
    } finally {
      authChecked = false; // re-check on next login
      authCheckPromise = null;
      stopTokenRefresh();
      // The cache and the stores belong to a session, not to the browser tab.
      // Emptied here as well as on the next sign-in, so nothing of somebody's
      // account is left sitting in memory after they have asked to leave.
      queryClient.clear();
      resetSessionState();
      logout();
      toast.success("Logged out");
      router.push(ROUTES.LOGIN);
    }
  }, [logout, router, queryClient]);

  const refreshToken = useCallback(async () => {
    try {
      const refreshResponse = await apiClient.post<{ access_token: string; message: string }>(
        "/auth/refresh",
      );
      useAuthStore.getState().setAccessToken(refreshResponse.access_token);
      const userData = await apiClient.get<User>("/auth/me");
      adoptUser(queryClient, setUser, userData);
      return true;
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        logout();
        router.push(ROUTES.LOGIN);
      }
      return false;
    }
  }, [logout, router, setUser, queryClient]);

  return {
    user,
    isAuthenticated,
    isLoading,
    login,
    register,
    logout: handleLogout,
    refreshToken,
  };
}
