import { renderHook } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type { NativeReadiness } from "@/lib/desktop/readiness";
import { useDesktopSetup } from "./use-desktop-setup";
const env = vi.hoisted(() => ({
  authenticated: true,
  loading: false,
  agentLoading: false,
  agentError: null as Error | null,
  agents: [{ status: "published", can_run: true }],
  modelLoading: false,
  modelError: null as Error | null,
  model: "ready" as string | null,
  configure: true,
  device: { linked: true, connected: true } as { linked: boolean; connected: boolean } | undefined,
  deviceError: null as Error | null,
  shellError: null as Error | null,
  shortcuts: [{ action: "quick_ask", accelerator: "Alt+Space", problem: null as string | null }],
  shellPresent: true,
  nativeError: null as Error | null,
  native: undefined as NativeReadiness | undefined,
  refetch: vi.fn(),
  retry: vi.fn(),
}));
vi.mock("./use-auth", () => ({
  useAuth: () => ({ isAuthenticated: env.authenticated, isLoading: env.loading }),
}));
vi.mock("@/stores", () => ({
  useAuthStore: (select: (s: { user: { id: string } }) => unknown) =>
    select({ user: { id: "me" } }),
}));
vi.mock("./use-organizations", () => ({ useTenantId: () => "org" }));
vi.mock("./use-permissions", () => ({ usePermissions: () => ({ can: () => true }) }));
vi.mock("./use-agents", () => ({
  useAgents: () => ({
    agents: env.agents,
    isLoading: env.agentLoading,
    error: env.agentError,
    refetch: env.refetch,
  }),
}));
vi.mock("./use-assistant", () => ({
  useAssistant: () => ({
    assistant: env.model ? { status: env.model, can_configure: env.configure } : null,
    isLoading: env.modelLoading,
    error: env.modelError,
    retry: env.retry,
  }),
}));
vi.mock("./use-desktop-readiness", () => ({
  useDesktopReadiness: () => ({
    status: { data: env.native, error: env.nativeError, refetch: env.refetch },
    request: {},
  }),
}));
vi.mock("./use-desktop", () => ({
  useDeviceStatus: () => ({ data: env.device, error: env.deviceError, refetch: env.refetch }),
  useDeviceLink: () => ({ link: {} }),
  useDesktopState: () => ({
    data: env.shellPresent ? { shortcuts: env.shortcuts, connection_revision: "shell" } : undefined,
    error: env.shellError,
    refetch: env.refetch,
  }),
}));
beforeEach(() => {
  Object.assign(env, {
    authenticated: true,
    loading: false,
    agentLoading: false,
    agentError: null,
    agents: [{ status: "published", can_run: true }],
    modelLoading: false,
    modelError: null,
    model: "ready",
    configure: true,
    device: { linked: true, connected: true },
    deviceError: null,
    shellError: null,
    shellPresent: true,
    shortcuts: [{ action: "quick_ask", accelerator: "Alt+Space", problem: null }],
    nativeError: null,
    native: {
      connection_revision: "native",
      screen_capture: "granted",
      accessibility: "granted",
      microphone: "granted",
      notifications: "granted",
    },
  });
  vi.clearAllMocks();
});
it("reports observed readiness and refreshes account facts only when signed in", () => {
  const { result, rerender } = renderHook(useDesktopSetup);
  const state = (key: string) => result.current.items.find((i) => i.key === key)?.state;
  expect(result.current.items.every((i) => i.state === "ready")).toBe(true);
  expect(result.current.revision).toBe("native");
  result.current.refresh();
  expect(env.refetch).toHaveBeenCalledTimes(4);
  expect(env.retry).toHaveBeenCalledOnce();
  env.loading = true;
  env.authenticated = false;
  env.native = undefined;
  env.device = undefined;
  env.shellPresent = false;
  rerender();
  for (const key of ["account", "agent", "model", "device", "shortcuts", "microphone"])
    expect(state(key)).toBe("checking");
  expect(result.current.revision).toBeUndefined();
  vi.clearAllMocks();
  result.current.refresh();
  expect(env.refetch).toHaveBeenCalledTimes(3);
  expect(env.retry).not.toHaveBeenCalled();
  env.loading = false;
  rerender();
  expect(state("account")).toBe("missing");
  env.authenticated = true;
  env.agentError = new Error("offline");
  env.modelError = new Error("offline");
  env.nativeError = new Error("offline");
  env.deviceError = new Error("offline");
  env.shellError = new Error("offline");
  rerender();
  for (const key of ["agent", "model", "device", "shortcuts", "screen_capture"])
    expect(state(key)).toBe("error");
});
it("distinguishes absent configuration, unsupported capabilities and checks in flight", () => {
  const { result, rerender } = renderHook(useDesktopSetup);
  const state = (key: string) => result.current.items.find((i) => i.key === key)?.state;
  env.agentLoading = true;
  env.modelLoading = true;
  rerender();
  expect(state("agent")).toBe("checking");
  expect(state("model")).toBe("checking");
  env.agentLoading = false;
  env.modelLoading = false;
  env.agents = [
    { status: "draft", can_run: true },
    { status: "published", can_run: false },
  ];
  env.model = "needs_model";
  env.device = { linked: false, connected: false };
  env.shortcuts = [];
  env.native = {
    connection_revision: "native",
    screen_capture: "denied",
    accessibility: "unsupported",
    microphone: "not_determined",
    notifications: "granted",
  };
  rerender();
  for (const key of ["agent", "model", "device", "shortcuts", "screen_capture", "microphone"])
    expect(state(key)).toBe("missing");
  expect(state("accessibility")).toBe("unsupported");
  env.model = null;
  env.configure = false;
  env.shortcuts = [{ action: "quick_ask", accelerator: "Alt+Space", problem: "taken" }];
  env.native = undefined;
  rerender();
  expect(state("model")).toBe("unsupported");
  expect(result.current.items.find((i) => i.key === "model")?.href).toBeUndefined();
  expect(state("shortcuts")).toBe("missing");
  expect(result.current.revision).toBe("shell");
});
