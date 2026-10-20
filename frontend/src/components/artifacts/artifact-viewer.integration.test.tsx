import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ArtifactViewer } from "./artifact-viewer";
import { ApiError } from "@/lib/api-error";
import { useOrgStore } from "@/stores";
import type {
  ArtifactData,
  ArtifactDetail as ArtifactDetailData,
  ArtifactVersion,
  BindingData,
} from "@/types/artifact";

/**
 * What a reader and a manager each get on one artifact's page.
 *
 * The page is the whole window and who reaches it lives behind Share. `can_edit`
 * is the server's answer, grants included, and it is the only thing that decides
 * whether a control that changes the artifact is drawn - a reader sees the page
 * and, behind Share, who else can, and has nothing to press.
 */

const useArtifactMock = vi.fn();
const useArtifactViewMock = vi.fn();
const useArtifactDataMock = vi.fn();
const orgs = vi.fn(() => [{ id: "o1", name: "Acme" }]);
const push = vi.fn();
const sharingPanel = vi.fn();

vi.mock("@/hooks/use-artifacts", () => ({
  useArtifact: (...args: unknown[]) => useArtifactMock(...args),
  useArtifactView: (...args: unknown[]) => useArtifactViewMock(...args),
  useArtifactData: (...args: unknown[]) => useArtifactDataMock(...args),
}));
vi.mock("@/lib/locale-navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/hooks", () => ({ useOrganizations: () => ({ orgs: orgs() }) }));
vi.mock("@/components/teams", () => ({
  OrganizationMenuItems: () => <div role="menuitem">Globex</div>,
}));
vi.mock("@/components/sharing/sharing-panel", () => ({
  SharingPanel: (props: { canManage: boolean; resourceType: string }) => {
    sharingPanel(props);
    return null;
  },
}));

function mutation() {
  return { mutate: vi.fn(), mutateAsync: vi.fn().mockResolvedValue(undefined), isPending: false };
}

function detail(overrides: Partial<ArtifactDetailData> = {}): ArtifactDetailData {
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
    current_version: null,
    created_at: "2026-09-01T10:00:00Z",
    updated_at: null,
    can_edit: false,
    live: false,
    bindings: [],
    public_link: {
      expires_at: null,
      pinned_version_id: null,
      pinned_version: null,
      password_protected: false,
      view_count: 0,
      last_viewed_at: null,
      embed_origins: [],
      embed_url: null,
    },
    ...overrides,
  };
}

function state(artifact: ArtifactDetailData | null, overrides: Record<string, unknown> = {}) {
  return {
    artifact,
    versions: [],
    isLoading: false,
    error: null,
    refetch: vi.fn(),
    enablePublicLink: mutation(),
    disablePublicLink: mutation(),
    updatePublicLink: mutation(),
    restoreVersion: mutation(),
    remove: mutation(),
    ...overrides,
  };
}

async function openShare() {
  await userEvent.click(screen.getByRole("button", { name: "Share" }));
  return screen.findByRole("dialog");
}

/**
 * The frame's two reads, held as constants: the frame memoizes its bridge on
 * them, and a mock answering a fresh object each render would hand the strip a
 * new bridge every time.
 */
const refetchView = vi.fn().mockResolvedValue(undefined);
const refetchData = vi.fn().mockResolvedValue(undefined);
const STATIC_VIEW = {
  isLoading: false,
  data: { url: "https://api/c/t", nonce: "n", live: false, version: { id: "v1" } },
  refetch: refetchView,
};
const LIVE_VIEW = {
  isLoading: false,
  data: { url: "https://api/c/t", nonce: "n", live: true, version: { id: "v2" } },
  refetch: refetchView,
};
const NO_DATA = {
  data: undefined,
  error: null,
  isError: false,
  isFetching: false,
  dataUpdatedAt: 0,
  refetch: refetchData,
};

function bound(overrides: Partial<BindingData> = {}): BindingData {
  return {
    status: "ok",
    reason: null,
    truncated: false,
    limit: null,
    count: 1,
    filters_dropped: false,
    fields: {},
    records: [],
    ...overrides,
  };
}

const MISSING = bound({ status: "unavailable", count: 0 });

/** A data query that answered, as the frame reads it. */
function dataQuery(bindings: Record<string, BindingData>) {
  const data: ArtifactData = { bindings, read_at: "2026-10-20T10:04:00Z" };
  return { ...NO_DATA, data, dataUpdatedAt: 1 };
}

/** A data query whose last read failed with `status`. */
function failedQuery(status: number) {
  return { ...NO_DATA, error: new ApiError(status, "No."), isError: true };
}

const V2: ArtifactVersion = {
  id: "v2",
  number: 2,
  media_type: "text/html",
  size_bytes: 1,
  run_id: null,
  created_at: "2026-09-22T10:00:00Z",
};
const V1: ArtifactVersion = { ...V2, id: "v1", number: 1, created_at: "2026-09-21T10:00:00Z" };

/** A page whose current version reads live data. */
function livePage(overrides: Partial<ArtifactDetailData> = {}) {
  return detail({ live: true, current_version: V2, ...overrides });
}

function postFromFrame(data: unknown) {
  const frame = screen.getByTitle("Weekly report") as HTMLIFrameElement;
  act(() => {
    window.dispatchEvent(new MessageEvent("message", { data, source: frame.contentWindow }));
  });
}

describe("ArtifactViewer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    useArtifactViewMock.mockReturnValue(STATIC_VIEW);
    useArtifactDataMock.mockReturnValue(NO_DATA);
    useOrgStore.setState({ activeOrgId: null });
    orgs.mockReturnValue([{ id: "o1", name: "Acme" }]);
  });

  it("opens the page itself, with the console reduced to one strip", () => {
    useArtifactMock.mockReturnValue(state(detail()));
    render(<ArtifactViewer artifactId="a1" initialVersionId={null} />);

    const frame = screen.getByTitle("Weekly report");
    expect(frame.getAttribute("src")).toBe("https://api/c/t");
    // The framed-card look is for a page inside the console; here it is the window.
    expect(frame.className).toContain("border-0");
    expect(screen.getByRole("heading", { name: "Weekly report" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to artifacts" })).toHaveAttribute(
      "href",
      "/artifacts",
    );
    // Nothing about who reaches it sits beside the page until Share is pressed.
    expect(sharingPanel).not.toHaveBeenCalled();
  });

  it("says in a word how far it reaches", () => {
    const { rerender } = render(<></>);
    for (const [overrides, label] of [
      [{}, "Only people with access"],
      [{ visibility: "org" }, "Whole organization"],
      [{ visibility: "org", public_url: "https://c/a/k" }, "Anyone with the link"],
    ] as const) {
      useArtifactMock.mockReturnValue(state(detail(overrides)));
      rerender(<ArtifactViewer artifactId="a1" initialVersionId={null} />);
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it("shows a reader who reaches it and nothing that changes it", async () => {
    useArtifactMock.mockReturnValue(state(detail()));
    render(<ArtifactViewer artifactId="a1" initialVersionId={null} />);

    expect(screen.queryByRole("button", { name: "More actions" })).toBeNull();
    const dialog = await openShare();
    expect(within(dialog).getByLabelText("Link to this page")).toHaveValue(
      `${window.location.origin}/artifacts/a1`,
    );
    expect(within(dialog).queryByRole("button", { name: "Create a public link" })).toBeNull();
    expect(sharingPanel).toHaveBeenCalledWith(
      expect.objectContaining({ resourceType: "artifact", resourceId: "a1", canManage: false }),
    );
  });

  it("names the organization in the page's address, so a member of two lands in the right one", async () => {
    useOrgStore.setState({ activeOrgId: "o1" });
    useArtifactMock.mockReturnValue(state(detail()));
    render(<ArtifactViewer artifactId="a1" initialVersionId={null} />);

    const dialog = await openShare();
    expect(within(dialog).getByLabelText("Link to this page")).toHaveValue(
      `${window.location.origin}/artifacts/a1?org=o1`,
    );
  });

  it("lets a manager turn the public link on from Share", async () => {
    const hooks = state(detail({ can_edit: true }));
    useArtifactMock.mockReturnValue(hooks);
    render(<ArtifactViewer artifactId="a1" initialVersionId={null} />);

    const dialog = await openShare();
    await userEvent.click(within(dialog).getByRole("button", { name: "Create a public link" }));
    expect(hooks.enablePublicLink.mutate).toHaveBeenCalled();
    expect(sharingPanel).toHaveBeenCalledWith(expect.objectContaining({ canManage: true }));
  });

  it("turns a live link off", async () => {
    const hooks = state(detail({ can_edit: true, public_url: "https://c/a/k" }));
    useArtifactMock.mockReturnValue(hooks);
    render(<ArtifactViewer artifactId="a1" initialVersionId={null} />);

    const dialog = await openShare();
    await userEvent.click(within(dialog).getByRole("button", { name: "Turn off" }));
    expect(hooks.disablePublicLink.mutate).toHaveBeenCalled();
  });

  it("holds the link controls while a public-link request is in flight", async () => {
    const hooks = state(detail({ can_edit: true }), {
      enablePublicLink: { ...mutation(), isPending: true },
    });
    useArtifactMock.mockReturnValue(hooks);
    render(<ArtifactViewer artifactId="a1" initialVersionId={null} />);

    const dialog = await openShare();
    expect(within(dialog).getByRole("button", { name: "Create a public link" })).toBeDisabled();
  });

  it("deletes from the menu after a confirmation and goes back to the list", async () => {
    const hooks = state(detail({ can_edit: true }));
    useArtifactMock.mockReturnValue(hooks);
    render(<ArtifactViewer artifactId="a1" initialVersionId={null} />);

    await userEvent.click(screen.getByRole("button", { name: "More actions" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Delete" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/artifacts"));
    expect(hooks.remove.mutateAsync).toHaveBeenCalled();
  });

  it("says an artifact that is gone or no longer shared is not available", () => {
    useArtifactMock.mockReturnValue(
      state(null, { error: new ApiError(404, "Artifact not found") }),
    );
    render(<ArtifactViewer artifactId="gone" initialVersionId={null} />);
    expect(screen.getByText("This artifact is not available")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
    // The way back stays, and nothing that acts on an artifact it could not load.
    expect(screen.getByRole("link", { name: "Back to artifacts" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Share" })).toBeNull();
    // Nowhere else to look for somebody in one organization.
    expect(screen.queryByRole("button", { name: "Switch organization" })).toBeNull();
  });

  it("offers another organization when the reader has one, since that is a 404 too", async () => {
    orgs.mockReturnValue([
      { id: "o1", name: "Acme" },
      { id: "o2", name: "Globex" },
    ]);
    useArtifactMock.mockReturnValue(
      state(null, { error: new ApiError(404, "Artifact not found") }),
    );
    render(<ArtifactViewer artifactId="elsewhere" initialVersionId={null} />);

    await userEvent.click(screen.getByRole("button", { name: "Switch organization" }));
    expect(await screen.findByRole("menuitem", { name: "Globex" })).toBeInTheDocument();
  });

  it("offers a retry for a failed request rather than calling the artifact gone", async () => {
    const hooks = state(null, { error: new ApiError(503, "Service unavailable") });
    useArtifactMock.mockReturnValue(hooks);
    render(<ArtifactViewer artifactId="a1" initialVersionId={null} />);

    expect(screen.queryByText("This artifact is not available")).toBeNull();
    expect(screen.getByText("This artifact could not be loaded")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(hooks.refetch).toHaveBeenCalled();
  });

  it("names the environment a page was published from", () => {
    useArtifactMock.mockReturnValue(state(detail({ environment_name: "staging" })));
    render(<ArtifactViewer artifactId="a1" initialVersionId={null} />);
    expect(screen.getByText("staging")).toBeInTheDocument();
  });

  it("offers a manager looking at an older version to restore it, then follows the latest", async () => {
    const versions: ArtifactVersion[] = [
      {
        id: "v2",
        number: 2,
        media_type: "text/html",
        size_bytes: 1,
        run_id: null,
        created_at: "2026-09-22T10:00:00Z",
      },
      {
        id: "v1",
        number: 1,
        media_type: "text/html",
        size_bytes: 1,
        run_id: null,
        created_at: "2026-09-21T10:00:00Z",
      },
    ];
    const hooks = state(detail({ can_edit: true, current_version: versions[0] }), { versions });
    hooks.restoreVersion.mutate.mockImplementation(
      (_id: string, options?: { onSuccess?: () => void }) => options?.onSuccess?.(),
    );
    useArtifactMock.mockReturnValue(hooks);
    render(<ArtifactViewer artifactId="a1" initialVersionId="v1" />);

    await userEvent.click(screen.getByRole("button", { name: "Restore this version" }));
    expect(hooks.restoreVersion.mutate).toHaveBeenCalledWith("v1", expect.anything());
    expect(screen.queryByRole("button", { name: "Restore this version" })).toBeNull();
  });

  it("offers no restore to a reader, or on the current version", () => {
    const current = {
      id: "v2",
      number: 2,
      media_type: "text/html" as const,
      size_bytes: 1,
      run_id: null,
      created_at: "2026-09-22T10:00:00Z",
    };
    const { rerender } = render(<></>);
    for (const [overrides, versionId] of [
      [{ can_edit: false, current_version: current }, "v1"],
      [{ can_edit: true, current_version: current }, "v2"],
      [{ can_edit: true, current_version: current }, null],
    ] as const) {
      useArtifactMock.mockReturnValue(state(detail(overrides)));
      rerender(
        <ArtifactViewer
          artifactId="a1"
          initialVersionId={versionId}
          key={String(versionId) + overrides.can_edit}
        />,
      );
      expect(screen.queryByRole("button", { name: "Restore this version" })).toBeNull();
    }
  });

  it("puts the link's settings behind Share for a manager, and saves them", async () => {
    const hooks = state(detail({ can_edit: true, public_url: "https://c/a/k" }));
    useArtifactMock.mockReturnValue(hooks);
    render(<ArtifactViewer artifactId="a1" initialVersionId={null} />);

    const dialog = await openShare();
    await userEvent.click(within(dialog).getByRole("button", { name: "Save link settings" }));
    expect(hooks.updatePublicLink.mutateAsync).toHaveBeenCalledWith({
      expires_at: null,
      pinned_version_id: null,
      embed_origins: [],
    });
  });

  it("shows a reader no link settings", async () => {
    useArtifactMock.mockReturnValue(state(detail({ public_url: "https://c/a/k" })));
    render(<ArtifactViewer artifactId="a1" initialVersionId={null} />);
    const dialog = await openShare();
    expect(within(dialog).queryByRole("button", { name: "Save link settings" })).toBeNull();
  });

  it("waits for the artifact before drawing anything", () => {
    useArtifactMock.mockReturnValue(state(null, { isLoading: true }));
    render(<ArtifactViewer artifactId="a1" initialVersionId={null} />);
    expect(screen.queryByText("This artifact is not available")).toBeNull();
    expect(screen.queryByRole("button", { name: "Share" })).toBeNull();
  });
});

describe("a live page in the viewer", () => {
  const AUTO = "agenticos:artifact-refresh:a1";

  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    useArtifactViewMock.mockReturnValue(LIVE_VIEW);
    useArtifactDataMock.mockReturnValue(dataQuery({ sales: bound() }));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  function open(artifact: ArtifactDetailData, overrides: Record<string, unknown> = {}) {
    useArtifactMock.mockReturnValue(state(artifact, overrides));
    return render(<ArtifactViewer artifactId="a1" initialVersionId={null} />);
  }

  /** Auto-refresh on every minute, on a fake clock the test moves. */
  function everyMinute() {
    localStorage.setItem(AUTO, "1");
    vi.useFakeTimers();
  }

  function minutesPass(minutes: number) {
    act(() => vi.advanceTimersByTime(minutes * 60_000));
  }

  it("shows Live, Refresh and when it was updated on a bound page", async () => {
    open(livePage());

    expect(screen.getByText("Live")).toBeInTheDocument();
    const refresh = screen.getByRole("button", { name: "Refresh" });
    expect(refresh).toHaveAttribute("title", expect.stringMatching(/^Updated \d{1,2}:\d{2}/));
    // Nothing needs attention, so nothing is said under the strip.
    expect(screen.queryByRole("status")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Refresh automatically" }));
    const menu = await screen.findByRole("menu");
    expect(within(menu).getByText(/^Updated \d{1,2}:\d{2}/)).toBeInTheDocument();
    expect(within(menu).getByRole("menuitemradio", { name: "Off" })).toBeChecked();
    expect(
      within(menu)
        .getAllByRole("menuitemradio")
        .map((item) => item.textContent),
    ).toEqual(["Off", "Every minute", "Every 5 minutes", "Every 15 minutes", "Every hour"]);
    await userEvent.click(within(menu).getByRole("menuitemradio", { name: "Every 5 minutes" }));
    expect(localStorage.getItem(AUTO)).toBe("5");
  });

  it("says nothing about live data on a page without any", () => {
    useArtifactViewMock.mockReturnValue(STATIC_VIEW);
    useArtifactDataMock.mockReturnValue(NO_DATA);
    open(detail({ current_version: V2 }));
    expect(screen.queryByText("Live")).toBeNull();
    expect(screen.queryByRole("button", { name: "Refresh" })).toBeNull();
  });

  it("names no time before the first read is in", async () => {
    useArtifactDataMock.mockReturnValue({ ...NO_DATA, isFetching: true });
    open(livePage());
    const refresh = screen.getByRole("button", { name: "Refresh" });
    expect(refresh).toHaveAttribute("title", "Refresh");
    expect(refresh).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Refresh automatically" }));
    expect(within(await screen.findByRole("menu")).queryByText(/Updated/)).toBeNull();
  });

  it("refreshes without reloading a page that listens", async () => {
    open(livePage());
    postFromFrame({ type: "agenticos:ready", n: "n", subscribes: true });

    await userEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(refetchData).toHaveBeenCalledTimes(1));
    expect(refetchView).not.toHaveBeenCalled();
  });

  it("reloads a page that does not listen", async () => {
    open(livePage());

    await userEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(refetchView).toHaveBeenCalledTimes(1));
    expect(refetchData).toHaveBeenCalledTimes(1);
    const [dataRead] = refetchData.mock.invocationCallOrder;
    const [viewRead] = refetchView.mock.invocationCallOrder;
    expect(dataRead).toBeLessThan(viewRead!);
  });

  it.each([403, 404])(
    "stops auto-refresh after a refusal until the viewer refreshes (%i)",
    (status) => {
      everyMinute();
      useArtifactDataMock.mockReturnValue(failedQuery(status));
      const { rerender } = open(livePage());

      minutesPass(5);
      expect(refetchData).not.toHaveBeenCalled();
      expect(screen.getByRole("status")).toHaveTextContent(
        "This page's live data is not available to you.",
      );

      // The viewer refreshes, and this time the read answers.
      fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
      expect(refetchData).toHaveBeenCalledTimes(1);
      useArtifactDataMock.mockReturnValue(dataQuery({ sales: bound() }));
      rerender(<ArtifactViewer artifactId="a1" initialVersionId={null} />);
      expect(screen.queryByRole("status")).toBeNull();

      minutesPass(1);
      expect(refetchData).toHaveBeenCalledTimes(2);
    },
  );

  it("stops auto-refresh for a reader when every source is unavailable", () => {
    everyMinute();
    // A reader is never told why: the reason does not reach them at all.
    useArtifactDataMock.mockReturnValue(dataQuery({ sales: MISSING, stock: MISSING }));
    open(livePage({ can_edit: false }));

    minutesPass(5);
    expect(refetchData).not.toHaveBeenCalled();
    expect(screen.getByRole("status")).toHaveTextContent("2 of 2 sources unavailable to you.");
  });

  it("keeps auto-refresh on while any source is ok", () => {
    everyMinute();
    useArtifactDataMock.mockReturnValue(dataQuery({ sales: bound(), stock: MISSING }));
    open(livePage());

    minutesPass(2);
    expect(refetchData).toHaveBeenCalledTimes(2);
  });

  it("keeps auto-refresh on after a busy answer", () => {
    everyMinute();
    useArtifactDataMock.mockReturnValue(failedQuery(429));
    open(livePage());

    expect(screen.getByRole("status")).toHaveTextContent("Busy, try again in a moment.");
    minutesPass(1);
    expect(refetchData).toHaveBeenCalledTimes(1);
  });

  it("says nothing more for any other failed read, and keeps refreshing", () => {
    everyMinute();
    useArtifactDataMock.mockReturnValue(failedQuery(500));
    open(livePage());

    expect(screen.queryByRole("status")).toBeNull();
    minutesPass(1);
    expect(refetchData).toHaveBeenCalledTimes(1);
  });

  it("tells a reader how many sources are unavailable, and an editor why", () => {
    useArtifactDataMock.mockReturnValue(
      dataQuery({ sales: bound(), escalations: MISSING, stock: MISSING }),
    );
    const { unmount } = open(livePage({ can_edit: false }));
    expect(screen.getByRole("status")).toHaveTextContent("2 of 3 sources unavailable to you.");
    expect(screen.queryByRole("link", { name: "Open the table" })).toBeNull();
    unmount();

    useArtifactDataMock.mockReturnValue(
      dataQuery({
        sales: bound(),
        escalations: bound({ status: "unavailable", count: 0, reason: "view_missing" }),
        stock: bound({ status: "unavailable", count: 0, reason: "timeout" }),
        orders: MISSING,
      }),
    );
    open(
      livePage({
        can_edit: true,
        bindings: [
          {
            name: "escalations",
            view_id: "vw1",
            table_id: "t1",
            fields: ["subject"],
            status: "unavailable",
            reason: "view_missing",
          },
        ],
      }),
    );
    const line = screen.getByRole("status");
    expect(line).toHaveTextContent("3 of 4 sources unavailable to you.");
    expect(line).toHaveTextContent("escalations: its saved view was deleted");
    expect(line).toHaveTextContent("stock: it took too long to read");
    expect(line).toHaveTextContent("orders: it could not be read");
    // Only a binding the page's detail names can be opened from here.
    const links = within(line).getAllByRole("link", { name: "Open the table" });
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute("href", "/tables/t1?viewId=vw1");
  });

  it("says live data is only on the current version, and opens it", async () => {
    const hooks = state(livePage({ can_edit: true }), { versions: [V2, V1] });
    useArtifactMock.mockReturnValue(hooks);
    render(<ArtifactViewer artifactId="a1" initialVersionId="v1" />);

    const notice = screen.getByRole("status");
    expect(notice).toHaveTextContent("Live data only on the current version.");
    // The older version reads nothing live, so nothing offers to refresh it.
    expect(screen.queryByRole("button", { name: "Refresh" })).toBeNull();
    expect(screen.queryByText("Live")).toBeNull();
    // An editor's Restore sits in the notice rather than in the strip as well.
    expect(screen.getAllByRole("button", { name: "Restore this version" })).toHaveLength(1);
    within(notice).getByRole("button", { name: "Restore this version" });

    await userEvent.click(within(notice).getByRole("button", { name: "Open current" }));
    expect(screen.queryByText("Live data only on the current version.")).toBeNull();
    expect(screen.getByRole("button", { name: "Refresh" })).toBeInTheDocument();
  });

  it("offers a reader on an older version only the current one", () => {
    useArtifactMock.mockReturnValue(state(livePage(), { versions: [V2, V1] }));
    render(<ArtifactViewer artifactId="a1" initialVersionId="v1" />);
    const notice = screen.getByRole("status");
    expect(within(notice).getByRole("button", { name: "Open current" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Restore this version" })).toBeNull();
  });

  it("labels the current version as live in the picker", async () => {
    open(livePage(), { versions: [V2, V1] });
    await userEvent.click(screen.getByRole("button", { name: "Version" }));
    expect(screen.getByRole("menuitemradio", { name: /^v2/ })).toHaveTextContent(
      "Current · live data",
    );
  });
});
