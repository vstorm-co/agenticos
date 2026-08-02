import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "./auth-store";
import type { User } from "@/types";

const createMockUser = (overrides?: Partial<User>): User => ({
  id: "test-id",
  email: "test@example.com",
  is_active: true,
  created_at: new Date().toISOString(),
  ...overrides,
});

describe("Auth Store", () => {
  beforeEach(() => {
    // Reset store before each test
    useAuthStore.setState({
      user: null,
      isAuthenticated: false,
      isLoading: false,
    });
  });

  it("should have initial state", () => {
    const state = useAuthStore.getState();
    expect(state.user).toBeNull();
    expect(state.isAuthenticated).toBe(false);
    expect(state.isLoading).toBe(false);
  });

  it("should set user on setUser", () => {
    const testUser = createMockUser();

    useAuthStore.getState().setUser(testUser);

    const state = useAuthStore.getState();
    expect(state.user).toEqual(testUser);
    expect(state.isAuthenticated).toBe(true);
  });

  it("should clear user on logout", () => {
    // First set a user
    useAuthStore.getState().setUser(createMockUser());

    // Then logout
    useAuthStore.getState().logout();

    const state = useAuthStore.getState();
    expect(state.user).toBeNull();
    expect(state.isAuthenticated).toBe(false);
  });

  it("should set loading state", () => {
    useAuthStore.getState().setLoading(true);
    expect(useAuthStore.getState().isLoading).toBe(true);

    useAuthStore.getState().setLoading(false);
    expect(useAuthStore.getState().isLoading).toBe(false);
  });
});

/**
 * Reading the session back from the server.
 *
 * The store is persisted, so a reload starts with whatever was there last time.
 * `checkAuth` is what reconciles that guess with the truth, and all three
 * outcomes have to land somewhere: signed in, signed out, and unreachable. The
 * third one is the interesting one - a network failure has to clear the session
 * rather than leave a persisted user on screen with every request behind it 401ing.
 */
describe("checkAuth", () => {
  beforeEach(() => {
    useAuthStore.setState({ user: null, isAuthenticated: false, isLoading: false });
  });

  afterEach(() => vi.unstubAllGlobals());

  it("adopts the user the server says is signed in", async () => {
    const user = createMockUser({ email: "kacper@example.com" });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(user) }),
    );

    await useAuthStore.getState().checkAuth();

    expect(useAuthStore.getState()).toMatchObject({
      user,
      isAuthenticated: true,
      isLoading: false,
    });
  });

  it("clears a persisted session the server no longer honours", async () => {
    // Which is what an expired refresh cookie looks like on a reload.
    useAuthStore.setState({ user: createMockUser(), isAuthenticated: true });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 401 }));

    await useAuthStore.getState().checkAuth();

    expect(useAuthStore.getState()).toMatchObject({
      user: null,
      isAuthenticated: false,
      isLoading: false,
    });
  });

  it("clears the session when the check could not be made at all", async () => {
    // Not left loading: a spinner that never resolves is worse than a login form.
    useAuthStore.setState({ user: createMockUser(), isAuthenticated: true });
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));

    await useAuthStore.getState().checkAuth();

    expect(useAuthStore.getState()).toMatchObject({
      user: null,
      isAuthenticated: false,
      isLoading: false,
    });
  });
});

describe("the rest of the session state", () => {
  it("keeps the access token in memory and drops it on logout", () => {
    // Never persisted: it is what the websocket authenticates with, and a token
    // in local storage outlives the tab it was minted for.
    useAuthStore.getState().setAccessToken("t-1");
    expect(useAuthStore.getState().accessToken).toBe("t-1");

    useAuthStore.getState().logout();
    expect(useAuthStore.getState().accessToken).toBeNull();
  });

  it("bumps the avatar version, which is what defeats the image cache", () => {
    // The URL does not change when somebody replaces their picture, so without
    // this the old one keeps rendering until a hard reload.
    const before = useAuthStore.getState().avatarVersion;

    useAuthStore.getState().bumpAvatarVersion();

    expect(useAuthStore.getState().avatarVersion).toBe(before + 1);
  });

  it("persists who is signed in but never the token", () => {
    // The whole reason `partialize` exists here.
    const persisted = useAuthStore.persist.getOptions().partialize?.({
      ...useAuthStore.getState(),
      accessToken: "t-1",
    }) as Record<string, unknown>;

    expect(persisted).toHaveProperty("isAuthenticated");
    expect(persisted).not.toHaveProperty("accessToken");
    // And the owner id, which has to survive a reload or the mount-time
    // adoption reads the same account as a new one and empties the persisted
    // organization and agent selection on every refresh.
    expect(persisted).toHaveProperty("sessionOwnerId");
  });

  it("stops loading as soon as it knows there is nobody signed in", () => {
    useAuthStore.setState({ isLoading: true });

    useAuthStore.getState().setUser(null);

    expect(useAuthStore.getState()).toMatchObject({ isAuthenticated: false, isLoading: false });
  });
});
