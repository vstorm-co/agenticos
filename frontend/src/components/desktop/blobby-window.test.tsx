import { act, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { qk } from "@/lib/query-keys";

import { BlobbyWindow } from "./blobby-window";
import { DESKTOP_STATE } from "./fixtures";

const env = vi.hoisted(() => ({
  listeners: new Map<string, (payload: unknown) => void>(),
  props: null as null | Record<string, unknown>,
  auth: { isAuthenticated: true, isLoading: false },
  report: vi.fn(),
  client: null as unknown,
}));
vi.mock("@/hooks/use-desktop", async () => {
  const { useQuery } = await import("@tanstack/react-query");
  return {
    useDesktopState: () =>
      useQuery({ queryKey: ["desktop", "state"], queryFn: async () => DESKTOP_STATE }),
    useShellEvent: (event: string, handler: (payload: unknown) => void) =>
      env.listeners.set(event, handler),
  };
});
vi.mock("@/hooks/use-auth", () => ({ useAuth: () => env.auth }));
vi.mock("@/hooks/use-blobby-activity", () => ({ useBlobbyActivity: () => ({ kind: "quiet" }) }));
vi.mock("@/hooks/use-live-updates", () => ({ useLiveUpdates: () => {} }));
vi.mock("@/hooks/use-reduced-motion", () => ({ useReducedMotion: () => false }));
vi.mock("@/lib/desktop/shell", async (original) => ({
  ...(await original<typeof import("@/lib/desktop/shell")>()),
  reportShellFailure: env.report,
}));
vi.mock("@/components/desktop/blobby", () => ({
  Blobby: (props: Record<string, unknown>) => {
    env.props = props;
    return <p>blobby</p>;
  },
}));

let client: QueryClient;
function mount() {
  client = new QueryClient();
  return render(
    <QueryClientProvider client={client}>
      <BlobbyWindow />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  env.listeners.clear();
  env.props = null;
  env.auth = { isAuthenticated: true, isLoading: false };
  env.report.mockClear();
});

describe("BlobbyWindow", () => {
  it("draws blobby from the desktop app's settings once it has them", async () => {
    mount();
    expect(await screen.findByText("blobby")).toBeInTheDocument();
    expect(env.props).toMatchObject({
      settings: DESKTOP_STATE.blobby,
      signedIn: true,
      heard: null,
    });
  });

  it("is told who it is now by the shell, and ignores a shape it cannot read", async () => {
    mount();
    await screen.findByText("blobby");
    const next = { ...DESKTOP_STATE.blobby, character: { kind: "cast", id: "sunny" } };
    act(() => env.listeners.get("desktop:blobby")?.(next));
    expect(client.getQueryData<typeof DESKTOP_STATE>(qk.desktop.state())?.blobby).toEqual(next);
    act(() => env.listeners.get("desktop:blobby")?.({ enabled: "yes" }));
    expect(env.report).toHaveBeenCalled();
  });

  it("leaves an unread cache alone when the shell speaks first", () => {
    env.auth = { isAuthenticated: false, isLoading: true };
    mount();
    act(() => env.listeners.get("desktop:blobby")?.(DESKTOP_STATE.blobby));
    expect(client.getQueryData(qk.desktop.state())).toBeUndefined();
  });

  it("passes on what the shell asks it to say, numbered so a repeat is said again", async () => {
    mount();
    await screen.findByText("blobby");
    act(() => env.listeners.get("desktop:say")?.("Allow screen recording."));
    act(() => env.listeners.get("desktop:say")?.("Allow screen recording."));
    act(() => env.listeners.get("desktop:say")?.(42));
    expect(env.props?.heard).toEqual({ text: "Allow screen recording.", id: 2 });
  });
});
