import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState, type ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AgentFilter } from "./agent-filter";
import { ArtifactCard } from "./artifact-card";
import {
  ARTIFACT_SANDBOX,
  ArtifactFrame,
  ArtifactFrameView,
  type DataBridge,
  readyFrom,
  requestedLink,
} from "./artifact-frame";
import { PublicArtifact } from "./public-artifact";
import { PublicLinkCard } from "./public-link-card";
import {
  EmbedSnippet,
  PublicLinkSettings,
  endOfDay,
  localDate,
  originLines,
} from "./public-link-settings";
import { VersionPicker } from "./version-picker";
import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import type {
  Artifact,
  ArtifactData,
  ArtifactPublicLink,
  ArtifactVersion,
  ArtifactView,
  BindingData,
} from "@/types/artifact";

const useArtifactViewMock = vi.fn();
const useArtifactDataMock = vi.fn();
const unlockMock = vi.fn();
vi.mock("@/hooks/use-artifacts", () => ({
  useArtifactView: (...args: unknown[]) => useArtifactViewMock(...args),
  useArtifactData: (...args: unknown[]) => useArtifactDataMock(...args),
  usePublicArtifactUnlock: () => unlockMock(),
}));
const toastError = vi.fn();
vi.mock("sonner", () => ({ toast: { error: (...args: unknown[]) => toastError(...args) } }));

function version(number: number, overrides: Partial<ArtifactVersion> = {}): ArtifactVersion {
  return {
    id: `v${number}`,
    number,
    media_type: "text/html",
    size_bytes: 10,
    run_id: null,
    restored_from: null,
    consent_state: "not_needed",
    created_at: "2026-09-22T10:00:00Z",
    ...overrides,
  };
}

function artifact(overrides: Partial<Artifact> = {}): Artifact {
  return {
    id: "a1",
    name: "weekly-report",
    title: "Weekly report",
    visibility: "private",
    owner_user_id: "u1",
    agent_id: "ag1",
    environment_id: null,
    environment_name: null,
    public_url: null,
    published_at: "2026-09-22T10:00:00Z",
    archived_at: null,
    live: false,
    current_version: version(3),
    created_at: "2026-09-01T10:00:00Z",
    updated_at: null,
    ...overrides,
  };
}

function link(overrides: Partial<ArtifactPublicLink> = {}): ArtifactPublicLink {
  return {
    expires_at: null,
    pinned_version_id: null,
    pinned_version: null,
    password_protected: false,
    view_count: 0,
    last_viewed_at: null,
    embed_origins: [],
    embed_url: null,
    ...overrides,
  };
}

/** A message as the framed page's platform script would post it. */
function postFromFrame(frame: HTMLIFrameElement, data: unknown) {
  act(() => {
    window.dispatchEvent(new MessageEvent("message", { data, source: frame.contentWindow }));
  });
}

/** A data query that has not answered, for a test about the frame alone. */
const IDLE_DATA = {
  data: undefined,
  error: null,
  isError: false,
  isFetching: false,
  dataUpdatedAt: 0,
  refetch: vi.fn(),
};

describe("the frame", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useArtifactDataMock.mockReturnValue(IDLE_DATA);
  });

  it("never grants the page this console's origin", () => {
    render(
      <ArtifactFrameView url="https://api.example/api/v1/artifact-content/t" title="Report" />,
    );
    const frame = screen.getByTitle("Report");
    expect(frame.getAttribute("sandbox")).toBe(ARTIFACT_SANDBOX);
    expect(ARTIFACT_SANDBOX).not.toContain("allow-same-origin");
    expect(ARTIFACT_SANDBOX).not.toContain("allow-top-navigation");
    // A popup is a navigation, which no `connect-src` governs - a way out.
    expect(ARTIFACT_SANDBOX).not.toContain("allow-popups");
    expect(frame.getAttribute("referrerpolicy")).toBe("no-referrer");
    expect(frame.getAttribute("src")).toBe("https://api.example/api/v1/artifact-content/t");
  });

  it("loads the version asked for from a fresh address", () => {
    useArtifactViewMock.mockReturnValue({
      isLoading: false,
      data: { url: "https://x/c/t", nonce: "n", live: false, version: version(2) },
    });
    render(<ArtifactFrame artifactId="a1" versionId="v2" title="Report" />);
    expect(useArtifactViewMock).toHaveBeenCalledWith("a1", "v2", true, false);
    // A page with no bindings asks for nothing.
    expect(useArtifactDataMock).toHaveBeenCalledWith("a1", "v2", false);
    expect(screen.getByTitle("Report").getAttribute("src")).toBe("https://x/c/t");
  });

  it("says a pruned or withdrawn version is not available", () => {
    useArtifactViewMock.mockReturnValue({ isLoading: false, data: undefined });
    render(<ArtifactFrame artifactId="a1" versionId="gone" title="Report" />);
    expect(screen.getByText("This version is not available")).toBeInTheDocument();
    expect(screen.queryByTitle("Report")).toBeNull();
  });

  it("lends a bridge an inline callback can keep in state without rendering forever", () => {
    useArtifactViewMock.mockReturnValue({
      isLoading: false,
      data: { url: "https://x/c/t", nonce: "n", live: false, version: version(2) },
    });
    let renders = 0;
    let lent: DataBridge | null = null;
    function Host() {
      const [bridge, setBridge] = useState<DataBridge | null>(null);
      renders += 1;
      lent = bridge;
      return (
        <ArtifactFrame
          artifactId="a1"
          versionId={null}
          title="Report"
          onBridge={(next) => setBridge(next)}
        />
      );
    }
    render(<Host />);
    expect(lent).not.toBeNull();
    expect(renders).toBeLessThan(5);
  });

  it("shows a skeleton while the address is minted", () => {
    useArtifactViewMock.mockReturnValue({ isLoading: true, data: undefined });
    const { container } = render(<ArtifactFrame artifactId="a1" versionId={null} title="R" />);
    expect(container.querySelector("iframe")).toBeNull();
  });
});

describe("a link inside the page", () => {
  afterEach(() => vi.restoreAllMocks());

  it("opens in a new tab only after a person reads the address and agrees", async () => {
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    render(<ArtifactFrameView url="https://api/c/t" title="Report" />);
    const frame = screen.getByTitle("Report") as HTMLIFrameElement;

    postFromFrame(frame, { type: "agenticos:open-link", href: "https://docs.example.com/q3" });
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("https://docs.example.com/q3")).toBeInTheDocument();
    expect(open).not.toHaveBeenCalled();

    await userEvent.click(within(dialog).getByRole("button", { name: "Open link" }));
    expect(open).toHaveBeenCalledWith(
      "https://docs.example.com/q3",
      "_blank",
      "noopener,noreferrer",
    );
  });

  it("keeps the address the person is reading while the page posts another", async () => {
    // A page may keep posting; taking the newest would swap the address being
    // checked for one the reader never saw, just before the click.
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    render(<ArtifactFrameView url="https://api/c/t" title="Report" />);
    const frame = screen.getByTitle("Report") as HTMLIFrameElement;

    postFromFrame(frame, { type: "agenticos:open-link", href: "https://docs.example.com/q3" });
    const dialog = await screen.findByRole("dialog");
    postFromFrame(frame, { type: "agenticos:open-link", href: "https://evil.example/leak" });

    expect(within(dialog).getByText("https://docs.example.com/q3")).toBeInTheDocument();
    expect(within(dialog).queryByText("https://evil.example/leak")).toBeNull();
    await userEvent.click(within(dialog).getByRole("button", { name: "Open link" }));
    expect(open).toHaveBeenCalledWith(
      "https://docs.example.com/q3",
      "_blank",
      "noopener,noreferrer",
    );
  });

  it("opens nothing when the person cancels", async () => {
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    render(<ArtifactFrameView url="https://api/c/t" title="Report" />);
    postFromFrame(screen.getByTitle("Report") as HTMLIFrameElement, {
      type: "agenticos:open-link",
      href: "https://docs.example.com/",
    });
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(open).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("asks nothing for a message from any other window", () => {
    render(<ArtifactFrameView url="https://api/c/t" title="Report" />);
    act(() => {
      window.dispatchEvent(
        new MessageEvent("message", {
          data: { type: "agenticos:open-link", href: "https://evil.example/" },
          source: window,
        }),
      );
    });
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

function liveView(
  nonce: string,
  number = 3,
  live = true,
  injected = false,
  awaitingConsent = false,
): ArtifactView {
  return {
    url: `https://c/${nonce}`,
    nonce,
    live,
    injected,
    awaiting_consent: awaitingConsent,
    bindings: live ? 1 : 0,
    expires_at: "",
    version: version(number),
  };
}

function bound(overrides: Partial<BindingData> = {}): BindingData {
  return {
    status: "ok",
    reason: null,
    truncated: false,
    limit: null,
    count: 1,
    fields: {},
    records: [{ id: "r1", region: "North" }],
    ...overrides,
  };
}

function answer(bindings: Record<string, BindingData>): ArtifactData {
  return { bindings, current: true, read_at: "2026-10-20T10:00:00Z" };
}

/** What the page receives for a binding: everything but the editor's reason. */
function forPage({ reason: _reason, ...rest }: BindingData) {
  return rest;
}

function ready(n: string, subscribes = false) {
  return { type: "agenticos:ready", n, subscribes };
}

const DATA_PATH = "/artifacts/a1/versions/v3/data";

/** Answers every read by its path, from the function the test gives. */
function serve(answerFor: (path: string) => unknown) {
  return vi
    .spyOn(apiClient, "get")
    .mockImplementation(((path: string) =>
      Promise.resolve().then(() => answerFor(path))) as typeof apiClient.get);
}

function paths() {
  return vi.mocked(apiClient.get).mock.calls.map(([path]) => path);
}

function renderLive(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrap = (node: ReactElement) => (
    <QueryClientProvider client={client}>{node}</QueryClientProvider>
  );
  const result = render(wrap(ui));
  return { client, rerender: (next: ReactElement) => result.rerender(wrap(next)) };
}

/** The frame once its address is in, loaded, with its window's inbox watched. */
async function loadedFrame(src: string) {
  await waitFor(() => expect(screen.getByTitle("Report").getAttribute("src")).toBe(src));
  const frame = screen.getByTitle("Report") as HTMLIFrameElement;
  const post = vi.spyOn(frame.contentWindow!, "postMessage").mockImplementation(() => {});
  fireEvent.load(frame);
  return { frame, post };
}

async function dataArrived(times = 1) {
  await waitFor(() => expect(paths().filter((path) => path === DATA_PATH)).toHaveLength(times));
  await act(async () => {});
}

type Bridge = {
  refresh: () => Promise<void>;
  status: { subscribes: boolean; data?: ArtifactData; served: unknown };
};

describe("the page's live data", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    const actual =
      await vi.importActual<typeof import("@/hooks/use-artifacts")>("@/hooks/use-artifacts");
    useArtifactViewMock.mockImplementation(actual.useArtifactView);
    useArtifactDataMock.mockImplementation(actual.useArtifactData);
  });
  afterEach(() => {
    vi.restoreAllMocks();
    useArtifactViewMock.mockReset();
    useArtifactDataMock.mockReset();
  });

  it("answers a page's ready with its data once both are in", async () => {
    let release!: (data: ArtifactData) => void;
    const pending = new Promise<ArtifactData>((resolve) => (release = resolve));
    serve((path) => (path === DATA_PATH ? pending : liveView("n1")));
    renderLive(<ArtifactFrame artifactId="a1" versionId={null} title="Report" />);
    const { frame, post } = await loadedFrame("https://c/n1");

    postFromFrame(frame, ready("n1"));
    expect(post).not.toHaveBeenCalled();

    await act(async () => release(answer({ sales: bound() })));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(post).toHaveBeenCalledWith(
      { type: "agenticos:data", n: "n1", bindings: { sales: forPage(bound()) } },
      "*",
    );
  });

  it("never fetches when a page says ready", async () => {
    serve((path) => (path === DATA_PATH ? answer({ sales: bound() }) : liveView("n1")));
    renderLive(<ArtifactFrame artifactId="a1" versionId={null} title="Report" />);
    const { frame, post } = await loadedFrame("https://c/n1");
    await dataArrived();

    for (let i = 0; i < 20; i++) postFromFrame(frame, ready("n1", i % 2 === 0));
    await act(async () => {});

    expect(paths().filter((path) => path === DATA_PATH)).toHaveLength(1);
    expect(post).toHaveBeenCalledTimes(1);
  });

  it("posts once however many readies arrive", async () => {
    serve((path) => (path === DATA_PATH ? answer({ sales: bound() }) : liveView("n1")));
    const { client } = renderLive(
      <ArtifactFrame artifactId="a1" versionId={null} title="Report" />,
    );
    const { frame, post } = await loadedFrame("https://c/n1");
    await dataArrived();

    for (let i = 0; i < 20; i++) postFromFrame(frame, ready("n1"));
    expect(post).toHaveBeenCalledTimes(1);

    // Nor does a new read reach a page that never said it listens.
    await act(() => client.refetchQueries({ queryKey: qk.artifacts.data("a1", "v3") }));
    await dataArrived(2);
    expect(post).toHaveBeenCalledTimes(1);
  });

  it("forgets the handshake when the frame loads again", async () => {
    let reads = 0;
    serve((path) => {
      if (path !== DATA_PATH) return liveView("n1");
      reads += 1;
      return answer({ sales: bound({ count: reads }) });
    });
    const { client } = renderLive(
      <ArtifactFrame artifactId="a1" versionId={null} title="Report" />,
    );
    const { frame, post } = await loadedFrame("https://c/n1");
    await dataArrived();
    postFromFrame(frame, ready("n1", true));
    expect(post).toHaveBeenCalledTimes(1);

    // A new document in the same frame has said nothing yet.
    fireEvent.load(frame);
    await act(() => client.refetchQueries({ queryKey: qk.artifacts.data("a1", "v3") }));
    await dataArrived(2);
    expect(post).toHaveBeenCalledTimes(1);

    postFromFrame(frame, ready("n1", true));
    expect(post).toHaveBeenCalledTimes(2);
    expect(post).toHaveBeenLastCalledWith(
      { type: "agenticos:data", n: "n1", bindings: { sales: forPage(bound({ count: 2 })) } },
      "*",
    );
  });

  it("refreshes a subscribing page in place on each fetch", async () => {
    let reads = 0;
    serve((path) => {
      if (path !== DATA_PATH) return liveView("n1");
      reads += 1;
      return answer({ sales: bound({ count: reads }) });
    });
    const onBridge = vi.fn<(bridge: Bridge) => void>();
    renderLive(
      <ArtifactFrame artifactId="a1" versionId={null} title="Report" onBridge={onBridge} />,
    );
    const { frame, post } = await loadedFrame("https://c/n1");
    await dataArrived();
    postFromFrame(frame, ready("n1", true));
    expect(onBridge.mock.lastCall?.[0].status.subscribes).toBe(true);

    await act(() => onBridge.mock.lastCall![0].refresh());
    await waitFor(() => expect(post).toHaveBeenCalledTimes(2));
    await act(() => onBridge.mock.lastCall![0].refresh());
    await waitFor(() => expect(post).toHaveBeenCalledTimes(3));

    expect(post).toHaveBeenLastCalledWith(
      { type: "agenticos:data", n: "n1", bindings: { sales: forPage(bound({ count: 3 })) } },
      "*",
    );
    // In place: the page was never minted again.
    expect(paths().filter((path) => path.includes("/view"))).toHaveLength(1);
  });

  it("refreshes in place again once a page says ready after its frame loads", async () => {
    // The page asks while it is still parsing, so its first ready can be
    // answered before the frame's load; the ready it sends on its own load is
    // what lets the console refresh it in place again.
    let reads = 0;
    serve((path) => {
      if (path !== DATA_PATH) return liveView("n1");
      reads += 1;
      return answer({ sales: bound({ count: reads }) });
    });
    const onBridge = vi.fn<(bridge: Bridge) => void>();
    renderLive(
      <ArtifactFrame artifactId="a1" versionId={null} title="Report" onBridge={onBridge} />,
    );
    await waitFor(() =>
      expect(screen.getByTitle("Report").getAttribute("src")).toBe("https://c/n1"),
    );
    const frame = screen.getByTitle("Report") as HTMLIFrameElement;
    const post = vi.spyOn(frame.contentWindow!, "postMessage").mockImplementation(() => {});
    await dataArrived();
    postFromFrame(frame, ready("n1", true));
    expect(post).toHaveBeenCalledTimes(1);

    fireEvent.load(frame);
    expect(onBridge.mock.lastCall?.[0].status.subscribes).toBe(false);
    postFromFrame(frame, ready("n1", true));
    expect(post).toHaveBeenCalledTimes(2);
    expect(onBridge.mock.lastCall?.[0].status.subscribes).toBe(true);

    await act(() => onBridge.mock.lastCall![0].refresh());
    await waitFor(() => expect(post).toHaveBeenCalledTimes(3));
    expect(post).toHaveBeenLastCalledWith(
      { type: "agenticos:data", n: "n1", bindings: { sales: forPage(bound({ count: 2 })) } },
      "*",
    );
    expect(paths().filter((path) => path.includes("/view"))).toHaveLength(1);
  });

  it("refetches the data before reloading a page that does not subscribe", async () => {
    let reads = 0;
    let mints = 0;
    serve((path) => {
      if (path === DATA_PATH) {
        reads += 1;
        return answer({ sales: bound({ count: reads }) });
      }
      mints += 1;
      return liveView(`n${mints}`);
    });
    const onBridge = vi.fn<(bridge: Bridge) => void>();
    renderLive(
      <ArtifactFrame artifactId="a1" versionId={null} title="Report" onBridge={onBridge} />,
    );
    const first = await loadedFrame("https://c/n1");
    await dataArrived();
    postFromFrame(first.frame, ready("n1"));
    expect(first.post).toHaveBeenCalledTimes(1);

    await act(() => onBridge.mock.lastCall![0].refresh());
    expect(paths()).toEqual([
      "/artifacts/a1/view?data=true",
      DATA_PATH,
      DATA_PATH,
      "/artifacts/a1/view?data=true",
    ]);
    // The page that does not listen was not handed the new read in place.
    expect(first.post).toHaveBeenCalledTimes(1);

    // The reloaded page asks, and gets the data read before it was minted.
    const second = await loadedFrame("https://c/n2");
    postFromFrame(second.frame, ready("n1"));
    expect(second.post).not.toHaveBeenCalled();
    postFromFrame(second.frame, ready("n2"));
    expect(second.post).toHaveBeenCalledWith(
      { type: "agenticos:data", n: "n2", bindings: { sales: forPage(bound({ count: 2 })) } },
      "*",
    );
  });

  it("reads nothing for a page served with its data, and refreshes it in place", async () => {
    let reads = 0;
    serve((path) => {
      if (path !== DATA_PATH) return liveView("n1", 3, true, true);
      reads += 1;
      return answer({ sales: bound({ count: reads }) });
    });
    const onBridge = vi.fn<(bridge: Bridge) => void>();
    renderLive(
      <ArtifactFrame artifactId="a1" versionId={null} title="Report" onBridge={onBridge} />,
    );
    const { frame, post } = await loadedFrame("https://c/n1");
    await act(async () => {});
    // The page carries its data: no first read, and its ready is answered with nothing.
    expect(paths()).toEqual(["/artifacts/a1/view?data=true"]);
    postFromFrame(frame, ready("n1", true));
    expect(post).not.toHaveBeenCalled();
    expect(onBridge.mock.lastCall?.[0].status.subscribes).toBe(true);

    // A refresh still reads through the data route and posts in place.
    await act(() => onBridge.mock.lastCall![0].refresh());
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(paths()).toEqual(["/artifacts/a1/view?data=true", DATA_PATH]);
    expect(post).toHaveBeenLastCalledWith(
      { type: "agenticos:data", n: "n1", bindings: { sales: forPage(bound({ count: 1 })) } },
      "*",
    );
    await act(() => onBridge.mock.lastCall![0].refresh());
    await waitFor(() => expect(post).toHaveBeenCalledTimes(2));
    expect(paths().filter((path) => path.includes("/view"))).toHaveLength(1);
  });

  it("never posts or shows a read cached from before an injected load was minted", async () => {
    let mints = 0;
    serve((path) => {
      if (path === DATA_PATH) return answer({ sales: bound({ count: 1 }) });
      mints += 1;
      return liveView(`n${mints}`, 3, true, true);
    });
    const onBridge = vi.fn<(bridge: Bridge) => void>();
    const { client } = renderLive(
      <ArtifactFrame artifactId="a1" versionId={null} title="Report" onBridge={onBridge} />,
    );
    const first = await loadedFrame("https://c/n1");
    postFromFrame(first.frame, ready("n1", true));
    // A refresh caches a read, and posts it in place to the page that listens.
    await act(() => onBridge.mock.lastCall![0].refresh());
    await waitFor(() => expect(first.post).toHaveBeenCalledTimes(1));
    expect(onBridge.mock.lastCall![0].status).toMatchObject({ data: { current: true } });

    // Consent confirmed or withdrawn: the page is minted again, its data is not read.
    await act(() => client.invalidateQueries({ queryKey: qk.artifacts.all() }));
    const second = await loadedFrame("https://c/n2");
    postFromFrame(second.frame, ready("n2", false));
    await act(async () => {});

    expect(second.post).not.toHaveBeenCalled();
    expect(onBridge.mock.lastCall![0].status.data).toBeUndefined();
    expect(paths().filter((path) => path === DATA_PATH)).toHaveLength(1);
  });

  it("reads again for an editor a read that settled before the load was minted", async () => {
    let mints = 0;
    let reads = 0;
    serve((path) => {
      if (path === DATA_PATH) {
        reads += 1;
        return answer({ sales: bound({ count: reads }) });
      }
      mints += 1;
      return liveView(`n${mints}`, 3, true, true);
    });
    const onBridge = vi.fn<(bridge: Bridge) => void>();
    const { client } = renderLive(
      <ArtifactFrame
        artifactId="a1"
        versionId={null}
        title="Report"
        onBridge={onBridge}
        fetchReasons
      />,
    );
    await loadedFrame("https://c/n1");
    await dataArrived(1);

    await act(() => client.invalidateQueries({ queryKey: qk.artifacts.all() }));
    await loadedFrame("https://c/n2");

    await dataArrived(2);
    expect(onBridge.mock.lastCall![0].status.data?.bindings.sales?.count).toBe(2);
  });

  it("tells the strip what the minted address says when nothing was read", async () => {
    serve(() => ({ ...liveView("n1", 3, true, true, true), bindings: 2 }));
    const onBridge = vi.fn<(bridge: Bridge) => void>();
    renderLive(
      <ArtifactFrame artifactId="a1" versionId={null} title="Report" onBridge={onBridge} />,
    );
    await loadedFrame("https://c/n1");

    expect(onBridge.mock.lastCall![0].status).toMatchObject({
      data: undefined,
      served: { bindings: 2, awaitingConsent: true },
    });
    expect(paths()).toEqual(["/artifacts/a1/view?data=true"]);
  });

  it("loads a page served with its data again, without a read of its own, when it does not subscribe", async () => {
    let mints = 0;
    serve((path) => {
      if (path === DATA_PATH) return answer({ sales: bound() });
      mints += 1;
      return liveView(`n${mints}`, 3, true, true);
    });
    const onBridge = vi.fn<(bridge: Bridge) => void>();
    renderLive(
      <ArtifactFrame artifactId="a1" versionId={null} title="Report" onBridge={onBridge} />,
    );
    await loadedFrame("https://c/n1");

    await act(() => onBridge.mock.lastCall![0].refresh());

    // The new load carries the data itself, so there is no read beside it.
    await loadedFrame("https://c/n2");
    expect(paths()).toEqual(["/artifacts/a1/view?data=true", "/artifacts/a1/view?data=true"]);
  });

  it("reloads a page with no live data without reading any", async () => {
    let mints = 0;
    serve(() => {
      mints += 1;
      return liveView(`n${mints}`, 3, false);
    });
    const onBridge = vi.fn<(bridge: Bridge) => void>();
    renderLive(
      <ArtifactFrame artifactId="a1" versionId={null} title="Report" onBridge={onBridge} />,
    );
    await loadedFrame("https://c/n1");

    await act(() => onBridge.mock.lastCall![0].refresh());

    await loadedFrame("https://c/n2");
    expect(paths()).toEqual(["/artifacts/a1/view?data=true", "/artifacts/a1/view?data=true"]);
  });

  it("drops a reply whose nonce belongs to the previous version", async () => {
    let releaseOld!: (data: ArtifactData) => void;
    const old = new Promise<ArtifactData>((resolve) => (releaseOld = resolve));
    serve((path) => {
      if (path === "/artifacts/a1/view?data=true") return liveView("n1", 3);
      if (path === "/artifacts/a1/view?version_id=v2") return liveView("n2", 2);
      if (path === DATA_PATH) return old;
      return answer({ older: bound({ count: 2 }) });
    });
    const { rerender } = renderLive(
      <ArtifactFrame artifactId="a1" versionId={null} title="Report" />,
    );
    const first = await loadedFrame("https://c/n1");
    postFromFrame(first.frame, ready("n1"));

    rerender(<ArtifactFrame artifactId="a1" versionId="v2" title="Report" />);
    const second = await loadedFrame("https://c/n2");
    await waitFor(() => expect(paths()).toContain("/artifacts/a1/versions/v2/data"));
    // The v1 document, late, and v1's records, later still.
    postFromFrame(second.frame, ready("n1"));
    await act(async () => releaseOld(answer({ sales: bound() })));
    expect(first.post).not.toHaveBeenCalled();
    expect(second.post).not.toHaveBeenCalled();

    postFromFrame(second.frame, ready("n2"));
    await waitFor(() => expect(second.post).toHaveBeenCalledTimes(1));
    expect(second.post).toHaveBeenCalledWith(
      { type: "agenticos:data", n: "n2", bindings: { older: forPage(bound({ count: 2 })) } },
      "*",
    );
  });

  it("refuses a ready from any other window", async () => {
    serve((path) => (path === DATA_PATH ? answer({ sales: bound() }) : liveView("n1")));
    renderLive(<ArtifactFrame artifactId="a1" versionId={null} title="Report" />);
    const { post } = await loadedFrame("https://c/n1");
    await dataArrived();

    act(() => {
      window.dispatchEvent(new MessageEvent("message", { data: ready("n1"), source: window }));
    });

    expect(post).not.toHaveBeenCalled();
  });

  it("posts hostile cell text as data", async () => {
    const hostile = {
      id: "r1",
      markup: "</script><img src=x onerror=alert(1)>",
      separator: "before after",
      emoji: "📈 up",
      long: "x".repeat(100_000),
    };
    serve((path) =>
      path === DATA_PATH ? answer({ sales: bound({ records: [hostile] }) }) : liveView("n1"),
    );
    renderLive(<ArtifactFrame artifactId="a1" versionId={null} title="Report" />);
    const { frame, post } = await loadedFrame("https://c/n1");
    await dataArrived();
    postFromFrame(frame, ready("n1"));

    const [message] = post.mock.calls[0] as [{ bindings: { sales: BindingData } }];
    const record = message.bindings.sales.records[0]!;
    expect(record.markup).toBe(hostile.markup);
    expect(record.separator).toBe(hostile.separator);
    expect(record.emoji).toBe(hostile.emoji);
    expect(record.long).toBe(hostile.long);
    expect(record).toEqual(hostile);
  });

  it("never passes the reason to the page", async () => {
    const gone = bound({ status: "unavailable", reason: "view_deleted", records: [] });
    serve((path) => (path === DATA_PATH ? answer({ sales: gone }) : liveView("n1")));
    renderLive(<ArtifactFrame artifactId="a1" versionId={null} title="Report" />);
    const { frame, post } = await loadedFrame("https://c/n1");
    await dataArrived();
    postFromFrame(frame, ready("n1"));

    const [message] = post.mock.calls[0] as [{ bindings: Record<string, object> }];
    expect(message.bindings.sales).not.toHaveProperty("reason");
    expect(message.bindings.sales).toEqual(forPage(gone));
  });

  it("keeps a binding named like a prototype key as the page's own", async () => {
    // As the server's JSON parses: an own key, never the object's prototype.
    const parsed = JSON.parse(
      `{"bindings": {"__proto__": ${JSON.stringify(bound())}}, "current": true, "read_at": ""}`,
    ) as ArtifactData;
    serve((path) => (path === DATA_PATH ? parsed : liveView("n1")));
    renderLive(<ArtifactFrame artifactId="a1" versionId={null} title="Report" />);
    const { frame, post } = await loadedFrame("https://c/n1");
    await dataArrived();
    postFromFrame(frame, ready("n1"));

    const [message] = post.mock.calls[0] as [{ bindings: object }];
    expect(Object.hasOwn(message.bindings, "__proto__")).toBe(true);
    expect(Object.getPrototypeOf(message.bindings)).toBe(Object.prototype);
  });

  it("moves a page on the current version onto a newer one an agent published", async () => {
    // v3 is open and listening; a run publishes v4, so v3's next read answers
    // not current. The frame mints the current version again, once, and the
    // reloaded page is answered with v4's data - never with v3's stale one.
    const NEWER = "/artifacts/a1/versions/v4/data";
    let mints = 0;
    let reads = 0;
    serve((path) => {
      if (path === DATA_PATH) {
        reads += 1;
        return { ...answer({ sales: bound() }), current: reads === 1 };
      }
      if (path === NEWER) return answer({ sales: bound({ count: 4 }) });
      mints += 1;
      return mints === 1 ? liveView("n1") : liveView("n2", 4);
    });
    const onBridge = vi.fn<(bridge: Bridge) => void>();
    const { client } = renderLive(
      <ArtifactFrame artifactId="a1" versionId={null} title="Report" onBridge={onBridge} />,
    );
    client.setQueryData(qk.artifacts.detail("a1"), artifact());
    client.setQueryData(qk.artifacts.versions("a1"), { items: [], total: 0 });
    const first = await loadedFrame("https://c/n1");
    await dataArrived();
    postFromFrame(first.frame, ready("n1", true));
    expect(first.post).toHaveBeenCalledTimes(1);

    await act(() => onBridge.mock.lastCall![0].refresh());
    const second = await loadedFrame("https://c/n2");
    await waitFor(() => expect(paths()).toContain(NEWER));

    expect(first.post).toHaveBeenCalledTimes(1);
    expect(paths().filter((path) => path === "/artifacts/a1/view?data=true")).toHaveLength(2);
    expect(client.getQueryState(qk.artifacts.detail("a1"))?.isInvalidated).toBe(true);
    expect(client.getQueryState(qk.artifacts.versions("a1"))?.isInvalidated).toBe(true);
    postFromFrame(second.frame, ready("n2", true));
    await waitFor(() =>
      expect(second.post).toHaveBeenCalledWith(
        { type: "agenticos:data", n: "n2", bindings: { sales: forPage(bound({ count: 4 })) } },
        "*",
      ),
    );
    await act(async () => {});
    expect(paths().filter((path) => path === "/artifacts/a1/view?data=true")).toHaveLength(2);
  });

  it("keeps a picked version where it is when a newer one is published", async () => {
    const stale = bound({ status: "unavailable", count: 0, records: [] });
    serve((path) =>
      path === DATA_PATH ? { ...answer({ sales: stale }), current: false } : liveView("n1"),
    );
    renderLive(<ArtifactFrame artifactId="a1" versionId="v3" title="Report" />);
    const { frame, post } = await loadedFrame("https://c/n1");
    await dataArrived();
    postFromFrame(frame, ready("n1"));

    expect(post).toHaveBeenCalledWith(
      { type: "agenticos:data", n: "n1", bindings: { sales: forPage(stale) } },
      "*",
    );
    expect(paths().filter((path) => path.includes("/view"))).toHaveLength(1);
  });

  it.each([403, 404])("answers with no data when the data answers %i", async (status) => {
    serve((path) => {
      if (path === DATA_PATH) throw new ApiError(status, "Not available.");
      return liveView("n1");
    });
    const onBridge = vi.fn<(bridge: Bridge) => void>();
    renderLive(
      <ArtifactFrame artifactId="a1" versionId={null} title="Report" onBridge={onBridge} />,
    );
    const { frame, post } = await loadedFrame("https://c/n1");
    postFromFrame(frame, ready("n1"));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith({ type: "agenticos:data", n: "n1", bindings: {} }, "*"),
    );
    expect(onBridge.mock.lastCall?.[0].status).toMatchObject({
      error: expect.objectContaining({ status }),
    });
  });
});

describe("what counts as a page's ready", () => {
  const frame = { contentWindow: window } as unknown as HTMLIFrameElement;
  const message = (data: unknown, source: unknown = window) =>
    new MessageEvent("message", { data, source: source as Window });

  it("takes the frame's own ready, with the nonce of this load", () => {
    expect(readyFrom(message(ready("n1", true)), frame, "n1")).toEqual({ subscribes: true });
    expect(readyFrom(message({ type: "agenticos:ready", n: "n1" }), frame, "n1")).toEqual({
      subscribes: false,
    });
  });

  it.each([
    ["no frame", ready("n1"), null],
    ["another window", ready("n1"), { contentWindow: {} }],
    ["not an object", "agenticos:ready", frame],
    ["null", null, frame],
    ["another type", { type: "agenticos:open-link", n: "n1" }, frame],
    ["another nonce", ready("n0"), frame],
  ])("refuses %s", (_label, data, target) => {
    expect(readyFrom(message(data), target as HTMLIFrameElement | null, "n1")).toBeNull();
  });
});

describe("what counts as a link request", () => {
  const frame = { contentWindow: window } as unknown as HTMLIFrameElement;
  const message = (data: unknown, source: unknown = window) =>
    new MessageEvent("message", { data, source: source as Window });

  it("takes an http or https address from the frame's own window", () => {
    expect(
      requestedLink(message({ type: "agenticos:open-link", href: "http://a.example/" }), frame),
    ).toBe("http://a.example/");
  });

  it.each([
    ["no frame", { type: "agenticos:open-link", href: "https://a/" }, null],
    ["not an object", "https://a/", frame],
    ["null", null, frame],
    ["another type", { type: "other", href: "https://a/" }, frame],
    ["no address", { type: "agenticos:open-link" }, frame],
    ["a script address", { type: "agenticos:open-link", href: "javascript:alert(1)" }, frame],
    ["not an address", { type: "agenticos:open-link", href: "::::" }, frame],
  ])("refuses %s", (_label, data, target) => {
    expect(requestedLink(message(data), target as HTMLIFrameElement | null)).toBeNull();
  });
});

describe("the list card", () => {
  it("says who else can read it", () => {
    useArtifactViewMock.mockReturnValue({ isLoading: false, data: undefined });
    render(
      <ArtifactCard artifact={artifact({ visibility: "org", public_url: "https://x/a/k" })} />,
    );
    expect(screen.getByText("Whole organization")).toBeInTheDocument();
    expect(screen.getByText("Public link")).toBeInTheDocument();
    expect(screen.getByRole("link").getAttribute("href")).toBe("/artifacts/a1");
    expect(screen.getByText(/Version 3/)).toBeInTheDocument();
  });

  it("marks a page with live data", () => {
    useArtifactViewMock.mockReturnValue({ isLoading: false, data: undefined });
    const { rerender } = render(<ArtifactCard artifact={artifact({ live: true })} />);
    expect(screen.getByText("Live")).toBeInTheDocument();
    rerender(<ArtifactCard artifact={artifact({ live: false })} />);
    expect(screen.queryByText("Live")).toBeNull();
  });

  it("stacks one sheet per earlier version and names the version on the page", () => {
    useArtifactViewMock.mockReturnValue({ isLoading: false, data: undefined });
    const { container } = render(<ArtifactCard artifact={artifact()} />);

    expect(container.querySelectorAll(".peek-sheet")).toHaveLength(2);
    expect(screen.getByText("v3")).toBeInTheDocument();
  });

  it("shows no reach badge for a private page", () => {
    render(<ArtifactCard artifact={artifact({ current_version: null })} />);
    expect(screen.queryByText("Whole organization")).toBeNull();
    expect(screen.queryByText("Public link")).toBeNull();
    expect(screen.getByText(/Version 0/)).toBeInTheDocument();
  });

  it("names the environment a page was published from, when it is not the default", () => {
    render(
      <ArtifactCard artifact={artifact({ current_version: null, environment_name: "staging" })} />,
    );
    expect(screen.getByText("staging")).toHaveAttribute("title", "Published from this environment");
  });

  it("marks an archived page and draws no thumbnail of a page that would not load", () => {
    useArtifactViewMock.mockReset();
    render(
      <ArtifactCard artifact={artifact({ archived_at: "2026-10-01T09:00:00Z", live: true })} />,
    );
    expect(screen.getByText("Archived")).toBeInTheDocument();
    // Archived serves nothing, so it is not live, whatever its bindings.
    expect(screen.queryByText("Live")).toBeNull();
    expect(useArtifactViewMock).not.toHaveBeenCalled();
    expect(screen.getByRole("link").getAttribute("href")).toBe("/artifacts/a1");
  });

  function withMenu(overrides: Partial<Artifact> = {}) {
    useArtifactViewMock.mockReturnValue({ isLoading: false, data: undefined });
    const actions = { onArchive: vi.fn(), onRestore: vi.fn(), onDelete: vi.fn() };
    render(<ArtifactCard artifact={artifact(overrides)} actions={actions} />);
    return actions;
  }

  it("offers a reader the page and nothing to act on", () => {
    useArtifactViewMock.mockReturnValue({ isLoading: false, data: undefined });
    render(<ArtifactCard artifact={artifact()} />);

    expect(screen.getByRole("link", { name: "Open Weekly report" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /More actions/ })).toBeNull();
  });

  it("archives a live page from its menu, without opening it", async () => {
    const actions = withMenu();
    const link = screen.getByRole("link", { name: "Open Weekly report" });
    const opened = vi.fn();
    link.addEventListener("click", opened);
    const trigger = screen.getByRole("button", { name: "More actions for Weekly report" });
    // The menu sits beside the link, never inside it.
    expect(link.contains(trigger)).toBe(false);

    await userEvent.click(trigger);
    expect(screen.queryByRole("menuitem", { name: "Restore" })).toBeNull();
    await userEvent.click(screen.getByRole("menuitem", { name: "Archive" }));

    expect(actions.onArchive).toHaveBeenCalled();
    expect(opened).not.toHaveBeenCalled();
  });

  it("restores an archived page from its menu", async () => {
    const actions = withMenu({ archived_at: "2026-10-01T09:00:00Z" });

    await userEvent.click(screen.getByRole("button", { name: "More actions for Weekly report" }));
    expect(screen.queryByRole("menuitem", { name: "Archive" })).toBeNull();
    await userEvent.click(screen.getByRole("menuitem", { name: "Restore" }));

    expect(actions.onRestore).toHaveBeenCalled();
  });

  it("deletes permanently, and says that is what it is", async () => {
    const actions = withMenu();

    await userEvent.click(screen.getByRole("button", { name: "More actions for Weekly report" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Delete permanently" }));

    expect(actions.onDelete).toHaveBeenCalled();
  });

  it("dims the card while its change is on the way", () => {
    useArtifactViewMock.mockReturnValue({ isLoading: false, data: undefined });
    const { container } = render(<ArtifactCard artifact={artifact()} busy />);

    expect(container.firstElementChild).toHaveClass("pointer-events-none");
  });
});

describe("the public link card", () => {
  it("offers a manager a link to create when there is none", async () => {
    const onEnable = vi.fn();
    render(
      <PublicLinkCard
        publicUrl={null}
        link={link()}
        canManage
        busy={false}
        onEnable={onEnable}
        onDisable={vi.fn()}
      />,
    );
    expect(
      screen.getByText("Only people this artifact is shared with can open it."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Opened|Not opened/)).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Create a public link" }));
    expect(onEnable).toHaveBeenCalled();
  });

  it("lets a manager replace or turn off a live link", async () => {
    const onEnable = vi.fn();
    const onDisable = vi.fn();
    render(
      <PublicLinkCard
        publicUrl="https://console.example/a/key"
        link={link()}
        canManage
        busy={false}
        onEnable={onEnable}
        onDisable={onDisable}
      />,
    );
    expect(screen.getByLabelText("Public link")).toHaveValue("https://console.example/a/key");
    expect(screen.getByText("Not opened yet")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Replace the link" }));
    await userEvent.click(screen.getByRole("button", { name: "Turn off" }));
    expect(onEnable).toHaveBeenCalled();
    expect(onDisable).toHaveBeenCalled();
  });

  it("shows a reader the link, how often it was opened, and nothing to press", () => {
    render(
      <PublicLinkCard
        publicUrl="https://console.example/a/key"
        link={link({ view_count: 4, last_viewed_at: "2026-09-29T10:00:00Z" })}
        canManage={false}
        busy={false}
        onEnable={vi.fn()}
        onDisable={vi.fn()}
      />,
    );
    expect(screen.getByText(/Opened 4 times, last/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Turn off" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Replace the link" })).toBeNull();
  });
});

describe("the version picker", () => {
  it("is not drawn for a page with one version and nothing pinned", () => {
    const { container } = render(
      <VersionPicker versions={[version(1)]} value={null} onChange={vi.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("pins a version and goes back to following the latest", async () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <VersionPicker versions={[version(2), version(1)]} value={null} onChange={onChange} />,
    );
    expect(screen.getByRole("button", { name: "Version" })).toHaveTextContent("v2Latest");
    await userEvent.click(screen.getByRole("button", { name: "Version" }));
    await userEvent.click(screen.getByRole("menuitemradio", { name: /^v1/ }));
    expect(onChange).toHaveBeenLastCalledWith("v1");

    rerender(<VersionPicker versions={[version(2), version(1)]} value="v1" onChange={onChange} />);
    expect(screen.getByRole("button", { name: "Version" })).toHaveTextContent("v1");
    await userEvent.click(screen.getByRole("button", { name: "Version" }));
    await userEvent.click(screen.getByRole("menuitemradio", { name: /Latest version/ }));
    expect(onChange).toHaveBeenLastCalledWith(null);
  });

  it("says which version is current and how large the others are", async () => {
    render(<VersionPicker versions={[version(2), version(1)]} value={null} onChange={vi.fn()} />);

    await userEvent.click(screen.getByRole("button", { name: "Version" }));

    expect(screen.getByRole("menuitemradio", { name: /^v2/ })).toHaveTextContent("Current");
    expect(screen.getByRole("menuitemradio", { name: /^v1/ })).toHaveTextContent(
      /\d+(\.\d+)? (B|KB)/,
    );
  });

  it("says which version a restored one was restored from, and nothing on a publish", async () => {
    render(
      <VersionPicker
        versions={[version(4, { restored_from: 2 }), version(3), version(2)]}
        value={null}
        onChange={vi.fn()}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Version" }));

    expect(screen.getByRole("menuitemradio", { name: /^v4/ })).toHaveTextContent(
      "v4 · restored from v2",
    );
    expect(screen.getByRole("menuitemradio", { name: /^v3/ })).not.toHaveTextContent(/restored/);
  });

  it("names nothing on the button for a pinned version that was pruned", () => {
    render(<VersionPicker versions={[version(2), version(1)]} value="gone" onChange={vi.fn()} />);

    expect(screen.getByRole("button", { name: "Version" })).not.toHaveTextContent(/v\d/);
  });
});

describe("the agent filter", () => {
  const agents = [
    { id: "ag1", name: "Reporter" },
    { id: "ag2", name: "Analyst" },
  ];

  it("is not drawn with one publisher and no filter on", () => {
    const { container } = render(
      <AgentFilter agents={agents.slice(0, 1)} value={null} onChange={vi.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("narrows to one agent and back to every agent", async () => {
    const onChange = vi.fn();
    const { rerender } = render(<AgentFilter agents={agents} value={null} onChange={onChange} />);
    await userEvent.click(screen.getByRole("combobox", { name: "Filter by agent" }));
    await userEvent.click(screen.getByRole("option", { name: "Analyst" }));
    expect(onChange).toHaveBeenLastCalledWith("ag2");

    rerender(<AgentFilter agents={[]} value="ag2" onChange={onChange} />);
    await userEvent.click(screen.getByRole("combobox", { name: "Filter by agent" }));
    await userEvent.click(screen.getByRole("option", { name: "Every agent" }));
    expect(onChange).toHaveBeenLastCalledWith(null);
  });
});

describe("the public link settings", () => {
  beforeEach(() => vi.clearAllMocks());

  function renderSettings(
    overrides: Partial<ArtifactPublicLink> = {},
    onSave = vi.fn().mockResolvedValue(undefined),
  ) {
    render(
      <PublicLinkSettings
        link={link(overrides)}
        versions={[version(2), version(1)]}
        saving={false}
        onSave={onSave}
      />,
    );
    return onSave;
  }

  it("saves the expiry, the pinned version and the embedding sites together", async () => {
    const onSave = renderSettings();
    fireEvent.change(screen.getByLabelText("Stops opening after"), {
      target: { value: "2026-10-14" },
    });
    await userEvent.click(screen.getByRole("combobox", { name: "Shows" }));
    await userEvent.click(screen.getByRole("option", { name: "v1" }));
    await userEvent.type(
      screen.getByLabelText("Sites that may embed it"),
      "https://a.example.com{enter}{enter} https://b.example.com ",
    );
    await userEvent.click(screen.getByRole("button", { name: "Save link settings" }));

    expect(onSave).toHaveBeenCalledWith({
      expires_at: endOfDay("2026-10-14"),
      pinned_version_id: "v1",
      embed_origins: ["https://a.example.com", "https://b.example.com"],
    });
  });

  it("clears what was set when the fields are emptied", async () => {
    const onSave = renderSettings({ expires_at: "2026-10-14T21:59:59Z", pinned_version_id: "v2" });
    fireEvent.change(screen.getByLabelText("Stops opening after"), { target: { value: "" } });
    await userEvent.click(screen.getByRole("combobox", { name: "Shows" }));
    await userEvent.click(screen.getByRole("option", { name: "Latest version" }));
    await userEvent.click(screen.getByRole("button", { name: "Save link settings" }));
    expect(onSave).toHaveBeenCalledWith({
      expires_at: null,
      pinned_version_id: null,
      embed_origins: [],
    });
  });

  it("shows a refusal under the field it names, not in a toast", async () => {
    const refusal = new ApiError(400, "Bad", {
      error: {
        code: "BAD_REQUEST",
        message: "Bad",
        details: { fields: [{ field: "embed_origins", message: "Not a site origin." }] },
      },
    });
    renderSettings({}, vi.fn().mockRejectedValue(refusal));
    await userEvent.click(screen.getByRole("button", { name: "Save link settings" }));
    expect(await screen.findByText("Not a site origin.")).toBeInTheDocument();
    expect(toastError).not.toHaveBeenCalled();
  });

  it("toasts a failure that names no field", async () => {
    renderSettings({}, vi.fn().mockRejectedValue(new ApiError(503, "Down")));
    await userEvent.click(screen.getByRole("button", { name: "Save link settings" }));
    expect(toastError).toHaveBeenCalled();
  });

  it("sets a password, and forgets what was typed once it is saved", async () => {
    const onSave = renderSettings();
    expect(screen.getByRole("button", { name: "Set password" })).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Password"), "hunter22");
    await userEvent.click(screen.getByRole("button", { name: "Set password" }));
    expect(onSave).toHaveBeenCalledWith({ password: "hunter22" });
    expect(screen.getByLabelText("Password")).toHaveValue("");
    expect(screen.queryByRole("button", { name: "Remove password" })).toBeNull();
  });

  it("keeps what was typed when the password is refused", async () => {
    const refusal = new ApiError(422, "Short", {
      detail: [{ loc: ["body", "password"], msg: "Too short", type: "string_too_short" }],
    });
    renderSettings({}, vi.fn().mockRejectedValue(refusal));
    await userEvent.type(screen.getByLabelText("Password"), "abc");
    await userEvent.click(screen.getByRole("button", { name: "Set password" }));
    expect(screen.getByLabelText("Password")).toHaveValue("abc");
  });

  it("changes or removes a password that is set, and says an embed needs none", async () => {
    const onSave = renderSettings({ password_protected: true });
    expect(screen.getByText(/cannot be embedded/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Change password" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Remove password" }));
    expect(onSave).toHaveBeenCalledWith({ password: null });
  });
});

describe("the embed code", () => {
  it.each([
    ["the link is off", link({ embed_origins: ["https://a.example.com"] })],
    ["no site may embed it", link({ embed_url: "https://api/e/k" })],
    [
      "it asks for a password",
      link({
        embed_url: "https://api/e/k",
        embed_origins: ["https://a"],
        password_protected: true,
      }),
    ],
  ])("is not offered when %s", (_label, settings) => {
    const { container } = render(<EmbedSnippet link={settings} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("is an iframe of the embed address", () => {
    render(
      <EmbedSnippet link={link({ embed_url: "https://api/e/k", embed_origins: ["https://a"] })} />,
    );
    expect(screen.getByText(/<iframe src="https:\/\/api\/e\/k"/)).toBeInTheDocument();
  });
});

describe("the settings' helpers", () => {
  it("reads a stored expiry as the reader's date and writes the end of that day", () => {
    const stored = endOfDay("2026-10-14");
    expect(stored).not.toBeNull();
    expect(localDate(stored)).toBe("2026-10-14");
    expect(localDate(null)).toBe("");
    expect(endOfDay("")).toBeNull();
  });

  it("reads one site per line and drops the blanks", () => {
    expect(originLines(" https://a \n\n https://b\n")).toEqual(["https://a", "https://b"]);
  });
});

describe("the public page", () => {
  beforeEach(() => vi.clearAllMocks());

  const opened = {
    password_required: false as const,
    title: "Weekly report",
    published_at: "2026-09-22T10:00:00Z",
    view: {
      url: "https://api/c/t",
      expires_at: "",
      nonce: "n",
      live: false,
      injected: false,
      awaiting_consent: false,
      bindings: 0,
      version: version(3),
    },
  };
  const locked = {
    password_required: true as const,
    title: null,
    published_at: null,
    view: null,
  };

  it("shows the page and when it was published, and nothing about who made it", () => {
    render(<PublicArtifact artifact={opened} publicKey="k" />);
    expect(screen.getByRole("heading", { name: "Weekly report" })).toBeInTheDocument();
    expect(screen.getByText(/Updated/)).toBeInTheDocument();
    expect(screen.getByTitle("Weekly report").getAttribute("src")).toBe("https://api/c/t");
  });

  it("asks for the password first and says nothing else about the page", async () => {
    const mutate = vi.fn();
    unlockMock.mockReturnValue({ mutate, data: undefined, error: null, isPending: false });
    render(<PublicArtifact artifact={locked} publicKey="k" />);

    expect(screen.getByRole("heading", { name: "This page is protected" })).toBeInTheDocument();
    expect(screen.queryByText("Weekly report")).toBeNull();
    expect(screen.getByRole("button", { name: "Open the page" })).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Password"), "hunter22{enter}");
    expect(mutate).toHaveBeenCalledWith("hunter22");
  });

  it("says a wrong password in the form", () => {
    unlockMock.mockReturnValue({
      mutate: vi.fn(),
      data: undefined,
      error: new ApiError(403, "That password is not right."),
      isPending: false,
    });
    render(<PublicArtifact artifact={locked} publicKey="k" />);
    expect(screen.getByText("That password is not right.")).toBeInTheDocument();
  });

  it("says any other failure as the failure it was", () => {
    unlockMock.mockReturnValue({
      mutate: vi.fn(),
      data: undefined,
      error: new ApiError(429, "Too many requests. Try again shortly."),
      isPending: false,
    });
    render(<PublicArtifact artifact={locked} publicKey="k" />);
    expect(screen.getByText(/Too many requests|too many/i)).toBeInTheDocument();
  });

  it("shows the page once the password was right", () => {
    unlockMock.mockReturnValue({ mutate: vi.fn(), data: opened, error: null, isPending: false });
    render(<PublicArtifact artifact={locked} publicKey="k" />);
    expect(screen.getByTitle("Weekly report")).toBeInTheDocument();
  });
});
