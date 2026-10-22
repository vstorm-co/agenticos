import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ArtifactViewer } from "./artifact-viewer";
import { ApiError } from "@/lib/api-error";
import { useOrgStore } from "@/stores";
import { useAuthStore } from "@/stores/auth-store";
import type { User } from "@/types";
import type {
  ArtifactConsent,
  ArtifactData,
  ArtifactDetail as ArtifactDetailData,
  ArtifactShareRequest,
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
const replace = vi.fn();
const sharingPanel = vi.fn();

const useArtifactDisclosureMock = vi.fn();
vi.mock("@/hooks/use-artifacts", () => ({
  useArtifact: (...args: unknown[]) => useArtifactMock(...args),
  useArtifactView: (...args: unknown[]) => useArtifactViewMock(...args),
  useArtifactData: (...args: unknown[]) => useArtifactDataMock(...args),
  useArtifactDisclosure: (...args: unknown[]) => useArtifactDisclosureMock(...args),
}));
const requestsMock = vi.fn();
const reviewMock = vi.fn();
const decline = { mutate: vi.fn(), isPending: false };
const approve = { mutate: vi.fn(), isPending: false };
const requestAccess = { mutate: vi.fn(), isPending: false, isSuccess: false };
vi.mock("@/hooks/use-artifact-requests", () => ({
  isConsentRequired: (error: unknown) =>
    error instanceof ApiError && error.code === "CONSENT_REQUIRED",
  useArtifactRequests: (...args: unknown[]) => requestsMock(...args),
  useArtifactRequestActions: () => ({ approve, decline }),
  useRequestAccess: () => requestAccess,
  useVersionReview: (...args: unknown[]) => reviewMock(...args),
}));
vi.mock("@/lib/locale-navigation", () => ({
  useRouter: () => ({ push, replace }),
  usePathname: () => "/artifacts/a1",
}));
vi.mock("@/hooks", () => ({
  useOrganizations: () => ({ orgs: orgs() }),
  useMembers: () => ({
    members: [{ user_id: "u2", email: "bea@example.com", full_name: null }],
  }),
}));
vi.mock("@/components/teams", () => ({
  OrganizationMenuItems: () => <div role="menuitem">Globex</div>,
}));
vi.mock("@/components/sharing/sharing-panel", () => ({
  SharingPanel: (props: {
    canManage: boolean;
    resourceType: string;
    mayGrantEditData?: boolean;
  }) => {
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
    archived_at: null,
    current_version: V2,
    created_at: "2026-09-01T10:00:00Z",
    updated_at: null,
    can_edit: false,
    may_change_owner: false,
    may_grant_edit_data: false,
    live: false,
    bindings: [],
    consent: null,
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
    archive: mutation(),
    unarchive: mutation(),
    remove: mutation(),
    confirmData: mutation(),
    withdrawConsent: mutation(),
    setAutoConsent: mutation(),
    changeOwner: mutation(),
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
  errorUpdatedAt: 0,
  refetch: refetchData,
};

function bound(overrides: Partial<BindingData> = {}): BindingData {
  return {
    status: "ok",
    reason: null,
    truncated: false,
    limit: null,
    count: 1,
    fields: {},
    records: [],
    ...overrides,
  };
}

const MISSING = bound({ status: "unavailable", count: 0 });

/** A data query that answered, as the frame reads it. */
function dataQuery(bindings: Record<string, BindingData>) {
  const data: ArtifactData = { bindings, current: true, read_at: "2026-10-20T10:04:00Z" };
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
  restored_from: null,
  consent_state: "not_needed",
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
    requestsMock.mockReturnValue({ requests: [], isLoading: false, error: null });
    reviewMock.mockReturnValue({ data: undefined, isLoading: true });
    requestAccess.isSuccess = false;
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

  it.each([true, false])(
    "hands the panel the server's answer on giving data-included access (%s)",
    async (allowed) => {
      useArtifactMock.mockReturnValue(
        state(detail({ can_edit: true, may_grant_edit_data: allowed })),
      );
      render(<ArtifactViewer artifactId="a1" initialVersionId={null} />);

      await openShare();

      expect(sharingPanel).toHaveBeenCalledWith(
        expect.objectContaining({ mayGrantEditData: allowed }),
      );
    },
  );

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

  it("offers Change owner from the menu only where the server says it may", async () => {
    useArtifactMock.mockReturnValue(state(detail({ can_edit: true })));
    const { unmount } = render(<ArtifactViewer artifactId="a1" initialVersionId={null} />);
    await userEvent.click(screen.getByRole("button", { name: "More actions" }));
    expect(screen.queryByRole("menuitem", { name: "Change owner" })).not.toBeInTheDocument();
    unmount();

    // Someone who may change the owner (an Owner or Admin, by role) but cannot edit the page still sees Change owner.
    const hooks = state(detail({ can_edit: false, may_change_owner: true }));
    useArtifactMock.mockReturnValue(hooks);
    render(<ArtifactViewer artifactId="a1" initialVersionId={null} />);
    await userEvent.click(screen.getByRole("button", { name: "More actions" }));
    expect(screen.queryByRole("menuitem", { name: "Delete" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("menuitem", { name: "Change owner" }));

    expect(await screen.findByRole("dialog")).toHaveTextContent("Change owner of Weekly report");
  });

  it("changes the owner to the chosen member and closes the dialog once the server took it", async () => {
    const hooks = state(detail({ can_edit: false, may_change_owner: true }));
    useArtifactMock.mockReturnValue(hooks);
    render(<ArtifactViewer artifactId="a1" initialVersionId={null} />);
    await userEvent.click(screen.getByRole("button", { name: "More actions" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Change owner" }));
    const dialog = await screen.findByRole("dialog");

    await userEvent.click(within(dialog).getByRole("combobox"));
    await userEvent.click(await screen.findByRole("option", { name: "bea@example.com" }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Continue" }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Change owner" }));

    expect(hooks.changeOwner.mutate).toHaveBeenCalledWith("u2", {
      onSuccess: expect.any(Function),
    });
    act(() => hooks.changeOwner.mutate.mock.calls[0]?.[1].onSuccess());
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
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

  it("archives from the menu after a confirmation that says what is kept and what stops", async () => {
    const hooks = state(detail({ can_edit: true, public_url: "https://c/a/k" }));
    hooks.archive.mutate.mockImplementation(
      (_variables: unknown, options?: { onSuccess?: () => void }) => options?.onSuccess?.(),
    );
    useArtifactMock.mockReturnValue(hooks);
    render(<ArtifactViewer artifactId="a1" initialVersionId={null} />);

    await userEvent.click(screen.getByRole("button", { name: "More actions" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Archive" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Archive Weekly report?")).toBeInTheDocument();
    expect(
      within(dialog).getByText(/its versions and its link are kept, but nobody can open it/),
    ).toBeInTheDocument();
    expect(within(dialog).getByText(/public link is turned off/)).toBeInTheDocument();
    expect(within(dialog).getByText(/restore it/)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Archive" }));

    expect(hooks.archive.mutate).toHaveBeenCalled();
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(hooks.remove.mutateAsync).not.toHaveBeenCalled();
  });

  it("offers a reader no Archive, and nothing else that changes the page", () => {
    useArtifactMock.mockReturnValue(state(detail({ can_edit: false })));
    render(<ArtifactViewer artifactId="a1" initialVersionId={null} />);
    expect(screen.queryByRole("button", { name: "More actions" })).toBeNull();
    expect(screen.queryByRole("menuitem", { name: "Archive" })).toBeNull();
  });

  it("shows an editor an archived page as when it was archived, with Restore", async () => {
    const hooks = state(detail({ can_edit: true, archived_at: "2026-10-01T09:00:00Z" }));
    useArtifactMock.mockReturnValue(hooks);
    render(<ArtifactViewer artifactId="a1" initialVersionId={null} />);

    expect(screen.getByText("Archived on Oct 1, 2026")).toBeInTheDocument();
    // An archived page serves nothing: no frame to load, nothing to share.
    expect(screen.queryByTitle("Weekly report")).toBeNull();
    expect(useArtifactViewMock).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Share" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Restore" }));
    expect(hooks.unarchive.mutate).toHaveBeenCalled();

    // Delete is still there; Archive is not.
    await userEvent.click(screen.getByRole("button", { name: "More actions" }));
    expect(screen.queryByRole("menuitem", { name: "Archive" })).toBeNull();
    await userEvent.click(await screen.findByRole("menuitem", { name: "Delete" }));
    expect(await screen.findByRole("dialog")).toHaveTextContent("Delete Weekly report?");
  });

  it("holds Restore while the restore is in flight", () => {
    const hooks = state(detail({ can_edit: true, archived_at: "2026-10-01T09:00:00Z" }), {
      unarchive: { ...mutation(), isPending: true },
    });
    useArtifactMock.mockReturnValue(hooks);
    render(<ArtifactViewer artifactId="a1" initialVersionId={null} />);
    expect(screen.getByRole("button", { name: "Restore" })).toBeDisabled();
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

  it("asks a member who may request access to do so, and shows nothing of the page", async () => {
    useArtifactMock.mockReturnValue(
      state(null, {
        error: new ApiError(403, "You don't have access to this page", {
          error: {
            code: "ACCESS_REQUESTABLE",
            message: "You don't have access to this page",
            details: { requested: false },
          },
        }),
      }),
    );
    const { container } = render(<ArtifactViewer artifactId="a1" initialVersionId={null} />);

    expect(screen.getByText("You don't have access to this page")).toBeInTheDocument();
    expect(screen.queryByText("This artifact is not available")).toBeNull();
    expect(screen.queryByTitle("Weekly report")).toBeNull();
    expect(container).not.toHaveTextContent("Weekly report");
    await userEvent.click(screen.getByRole("button", { name: "Request access" }));
    expect(requestAccess.mutate).toHaveBeenCalledWith(null);
  });

  it("says the request is made when the server already holds one", () => {
    useArtifactMock.mockReturnValue(
      state(null, {
        error: new ApiError(403, "No access", {
          error: {
            code: "ACCESS_REQUESTABLE",
            message: "No access",
            details: { requested: true },
          },
        }),
      }),
    );
    render(<ArtifactViewer artifactId="a1" initialVersionId={null} />);

    expect(screen.getByText("Access requested")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Request access" })).toBeNull();
  });

  it("keeps the not-found page for any other refusal", () => {
    useArtifactMock.mockReturnValue(
      state(null, {
        error: new ApiError(403, "Nope", {
          error: { code: "FORBIDDEN", message: "Nope", details: null },
        }),
      }),
    );
    render(<ArtifactViewer artifactId="a1" initialVersionId={null} />);

    expect(screen.queryByText("You don't have access to this page")).toBeNull();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
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
        restored_from: null,
        consent_state: "not_needed",
        created_at: "2026-09-22T10:00:00Z",
      },
      {
        id: "v1",
        number: 1,
        media_type: "text/html",
        size_bytes: 1,
        run_id: null,
        restored_from: null,
        consent_state: "not_needed",
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
      restored_from: null,
      consent_state: "not_needed" as const,
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

  it.each([
    ["every source answers", dataQuery({ sales: bound() }), "flowing"],
    [
      "some sources are unavailable",
      dataQuery({ sales: bound(), costs: bound({ status: "unavailable" }) }),
      "partial",
    ],
    ["the first read is still to come", NO_DATA, "steady"],
    ["a read failed for now", failedQuery(500), "steady"],
  ])("draws the Live badge's dot by its data when %s", (_, query, health) => {
    useArtifactDataMock.mockReturnValue(query);
    open(livePage());
    expect(screen.getByText("Live").closest("[data-health]")).toHaveAttribute(
      "data-health",
      health,
    );
  });

  it.each([
    ["no source is available", dataQuery({ sales: bound({ status: "unavailable" }) })],
    ["the data was refused", failedQuery(403)],
  ])("shows no Live badge to a viewer when %s", (_, query) => {
    useArtifactDataMock.mockReturnValue(query);
    open(livePage());
    expect(screen.queryByText("Live")).toBeNull();
    // The line under the strip is what says why.
    expect(screen.getByRole("status")).toBeInTheDocument();
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

  describe("served with its data", () => {
    const INJECTED = {
      ...LIVE_VIEW,
      dataUpdatedAt: 1,
      data: { ...LIVE_VIEW.data, injected: true, bindings: 2, awaiting_consent: true },
    };

    it("says the data waits for consent, and stops auto-refresh, with nothing read", () => {
      everyMinute();
      useArtifactViewMock.mockReturnValue(INJECTED);
      useArtifactDataMock.mockReturnValue(NO_DATA);
      open(livePage({ can_edit: false }));

      expect(screen.getByRole("status")).toHaveTextContent(
        "This page's data appears once its owner confirms sharing it.",
      );
      expect(screen.queryByText("Live")).toBeNull();
      minutesPass(5);
      expect(refetchData).not.toHaveBeenCalled();
    });

    it("leaves the waiting to the consent strip when the viewer has one", () => {
      useArtifactViewMock.mockReturnValue(INJECTED);
      useArtifactDataMock.mockReturnValue(NO_DATA);
      open(livePage({ can_edit: false, consent: consent() }));

      expect(
        screen.queryByText("This page's data appears once its owner confirms sharing it."),
      ).toBeNull();
    });

    it("keeps auto-refresh on for a page whose data does not wait", () => {
      everyMinute();
      useArtifactViewMock.mockReturnValue({
        ...INJECTED,
        data: { ...INJECTED.data, awaiting_consent: false },
      });
      useArtifactDataMock.mockReturnValue(NO_DATA);
      open(livePage({ can_edit: false }));

      expect(screen.queryByRole("status")).toBeNull();
      expect(screen.getByText("Live")).toBeInTheDocument();
      // The page does not listen, so each tick loads it again, data written in.
      minutesPass(2);
      expect(refetchView).toHaveBeenCalledTimes(2);
    });

    it("reads the data once for an editor only", () => {
      useArtifactViewMock.mockReturnValue({
        ...INJECTED,
        data: { ...INJECTED.data, awaiting_consent: false },
      });
      useArtifactDataMock.mockReturnValue(NO_DATA);
      const { unmount } = open(livePage({ can_edit: true }));
      expect(useArtifactDataMock).toHaveBeenLastCalledWith("a1", "v2", true);
      unmount();
      open(livePage({ can_edit: false }));
      expect(useArtifactDataMock).toHaveBeenLastCalledWith("a1", "v2", false);
    });
  });

  it("keeps auto-refresh on, and says nothing, while it moves to a newer version", () => {
    // Every source of a version no longer current answers unavailable; that is
    // the console catching up with a republish, not a page that cannot load.
    everyMinute();
    useArtifactDataMock.mockReturnValue({
      ...dataQuery({ sales: MISSING, stock: MISSING }),
      data: { bindings: { sales: MISSING, stock: MISSING }, current: false, read_at: "" },
    });
    open(livePage({ can_edit: false }));

    expect(screen.queryByRole("status")).toBeNull();
    minutesPass(2);
    expect(refetchData).toHaveBeenCalledTimes(2);
  });

  it("names one source in the singular", () => {
    useArtifactDataMock.mockReturnValue(dataQuery({ sales: MISSING }));
    open(livePage({ can_edit: false }));
    expect(screen.getByRole("status")).toHaveTextContent("1 of 1 source unavailable to you.");
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
        escalations: bound({
          status: "unavailable",
          count: 0,
          reason: "source_changed",
          changed: "Priority",
        }),
        stock: bound({ status: "unavailable", count: 0, reason: "timeout" }),
        orders: MISSING,
        returns: bound({ status: "unavailable", count: 0, reason: "creator_lost_access" }),
      }),
    );
    open(
      livePage({
        can_edit: true,
        bindings: [{ name: "escalations", table_id: "t1", fields: ["subject"] }],
      }),
    );
    const line = screen.getByRole("status");
    expect(line).toHaveTextContent("4 of 5 sources unavailable to you.");
    expect(line).toHaveTextContent(
      "escalations: Priority changed since it was published - publish the page again",
    );
    expect(line).toHaveTextContent("stock: it took too long to read");
    expect(line).toHaveTextContent("orders: it could not be read");
    expect(line).toHaveTextContent("returns: the page's owner can no longer read a table it reads");
    // Only a binding the page's detail names can be opened from here.
    const links = within(line).getAllByRole("link", { name: "Open the table" });
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute("href", "/tables/t1");
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

  describe("the address", () => {
    beforeEach(() => {
      replace.mockClear();
    });
    afterEach(() => {
      window.history.replaceState(null, "", "/");
    });

    it("drops the version once Open current is pressed, so a reload opens the current one", async () => {
      window.history.replaceState(null, "", "/artifacts/a1?version=v1&org=o1");
      useArtifactMock.mockReturnValue(state(livePage({ can_edit: true }), { versions: [V2, V1] }));
      render(<ArtifactViewer artifactId="a1" initialVersionId="v1" />);
      expect(replace).not.toHaveBeenCalled();

      await userEvent.click(
        within(screen.getByRole("status")).getByRole("button", { name: "Open current" }),
      );
      expect(replace).toHaveBeenLastCalledWith("/artifacts/a1?org=o1", { scroll: false });
    });

    it("names the version picked, so a reload opens it again", async () => {
      window.history.replaceState(null, "", "/artifacts/a1");
      useArtifactMock.mockReturnValue(state(livePage(), { versions: [V2, V1] }));
      render(<ArtifactViewer artifactId="a1" initialVersionId={null} />);
      expect(replace).not.toHaveBeenCalled();

      await userEvent.click(screen.getByRole("button", { name: "Version" }));
      await userEvent.click(screen.getByRole("menuitemradio", { name: /^v1/ }));
      expect(replace).toHaveBeenLastCalledWith("/artifacts/a1?version=v1", { scroll: false });
    });

    it("opens a link to the current version as the current one, which follows a republish", () => {
      window.history.replaceState(null, "", "/artifacts/a1?version=v2");
      render(<ArtifactViewer artifactId="a1" initialVersionId="v2" />);

      // V2 is current: no older-version notice, live data is read, the pin is dropped.
      expect(screen.queryByText("Live data only on the current version.")).toBeNull();
      expect(screen.getByRole("button", { name: "Refresh" })).toBeInTheDocument();
      expect(replace).toHaveBeenLastCalledWith("/artifacts/a1", { scroll: false });
    });
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

/** Where a bound page's latest version stands, for a caller served it. */
function consent(overrides: Partial<ArtifactConsent> = {}): ArtifactConsent {
  return {
    version: 2,
    state: "pending",
    fingerprint: "f".repeat(64),
    automatic: false,
    grown: [],
    via: null,
    audience_version: 1,
    shared: true,
    owner_name: "Olga Owner",
    withdrawn_at: null,
    auto_consent: false,
    may_confirm: false,
    may_withdraw: false,
    may_enable_auto_consent: false,
    may_disable_auto_consent: false,
    ...overrides,
  };
}

describe("a page's consent in the viewer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useArtifactViewMock.mockReturnValue(LIVE_VIEW);
    useArtifactDataMock.mockReturnValue(
      dataQuery({ sales: bound({ status: "unavailable", count: 0, reason: "awaiting_consent" }) }),
    );
    useAuthStore.setState({ user: { id: "u1", email: "olga@example.com" } as User });
  });
  afterEach(() => {
    useAuthStore.setState({ user: null });
  });

  function open(artifact: ArtifactDetailData, overrides: Record<string, unknown> = {}) {
    const hooks = state(artifact, overrides);
    useArtifactMock.mockReturnValue(hooks);
    render(<ArtifactViewer artifactId="a1" initialVersionId={null} />);
    return hooks;
  }

  it("tells the audience a page none of which is theirs yet is not available", () => {
    open(detail({ current_version: null }));

    expect(screen.getByText("This page isn't available yet")).toBeVisible();
    expect(screen.getByText("Its owner hasn't confirmed the data it shares.")).toBeVisible();
    expect(screen.queryByTitle("Weekly report")).toBeNull();
  });

  it("tells the audience once, for the whole page, that its data waits for the owner", () => {
    open(livePage({ can_edit: false }));

    expect(screen.getByRole("status")).toHaveTextContent(
      "This page's data appears once its owner confirms sharing it.",
    );
    expect(screen.queryByText(/sources unavailable/)).toBeNull();
  });

  it("asks the owner to confirm and confirms the fingerprint the dialog showed", async () => {
    useArtifactDisclosureMock.mockReturnValue({
      data: {
        version: 2,
        fingerprint: "a".repeat(64),
        bindings: {},
        parts: {},
        tables: ["Deals"],
        visibility: "private",
        people: [],
        groups: [],
        roles: ["owner"],
        problem: null,
      },
      isLoading: false,
      refetch: vi.fn(),
    });
    const hooks = open(livePage({ can_edit: true, consent: consent({ may_confirm: true }) }));

    const strip = screen.getByRole("status");
    expect(strip).toHaveTextContent("The audience still sees v1 until you confirm.");
    await userEvent.click(within(strip).getByRole("button", { name: "Confirm data" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Confirm data" }));

    expect(hooks.confirmData.mutateAsync).toHaveBeenCalledWith({
      versionId: "v2",
      fingerprint: "a".repeat(64),
    });
  });

  it("lets an editor withdraw from the menu, after saying what it does", async () => {
    useAuthStore.setState({ user: { id: "u2", email: "ed@example.com" } as User });
    const hooks = open(
      livePage({
        can_edit: true,
        consent: consent({ state: "consented", may_withdraw: true, owner_name: null }),
      }),
    );

    await userEvent.click(screen.getByRole("button", { name: "More actions" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Stop sharing data" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("until its owner confirms it again");
    await userEvent.click(within(dialog).getByRole("button", { name: "Stop sharing data" }));

    expect(hooks.withdrawConsent.mutate).toHaveBeenCalledOnce();
  });

  it("lets an editor withdraw from the strip while a newer version waits", async () => {
    useAuthStore.setState({ user: { id: "u2", email: "ed@example.com" } as User });
    const hooks = open(livePage({ can_edit: true, consent: consent({ may_withdraw: true }) }));
    hooks.withdrawConsent.mutate.mockImplementation(
      (_: undefined, { onSuccess }: { onSuccess: () => void }) => onSuccess(),
    );

    const strip = screen.getByRole("status");
    expect(strip).toHaveTextContent("The audience still sees v1 until Olga Owner confirms.");
    await userEvent.click(within(strip).getByRole("button", { name: "Stop sharing data" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Stop sharing data" }));

    expect(hooks.withdrawConsent.mutate).toHaveBeenCalledWith(undefined, {
      onSuccess: expect.any(Function),
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("offers no Withdraw in the menu while the audience reads no data", async () => {
    open(livePage({ can_edit: true, consent: consent({ may_withdraw: true, shared: false }) }));

    await userEvent.click(screen.getByRole("button", { name: "More actions" }));

    expect(screen.queryByRole("menuitem", { name: "Stop sharing data" })).toBeNull();
  });

  it("puts auto-consent in Share for the page's owner", async () => {
    const hooks = open(
      livePage({ can_edit: true, consent: consent({ may_enable_auto_consent: true }) }),
    );

    const share = await openShare();

    await userEvent.click(
      within(share).getByRole("switch", { name: "Don't ask for consent on republish" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Turn on" }));

    expect(hooks.setAutoConsent.mutate).toHaveBeenCalledWith(
      { enabled: true, confirmed: "auto_consent.v1" },
      { onSuccess: expect.any(Function) },
    );
  });

  it("marks where each version's consent stands in the picker", async () => {
    open(livePage({ can_edit: true, consent: consent() }), {
      versions: [
        { ...V2, consent_state: "pending" },
        { ...V1, consent_state: "consented" },
      ],
    });

    await userEvent.click(screen.getByRole("button", { name: "Version" }));

    expect(screen.getByRole("menuitemradio", { name: /^v2/ })).toHaveTextContent(
      "awaiting consent",
    );
    expect(screen.getByRole("menuitemradio", { name: /^v1/ })).toHaveTextContent("data shared");
  });
});

describe("ArtifactViewer requests", () => {
  const VERSION_REQUEST: ArtifactShareRequest = {
    id: "r1",
    artifact_id: "a1",
    kind: "version",
    status: "pending",
    requester_user_id: "u2",
    requester_name: "Bea Builder",
    version_id: "v3",
    version_number: 3,
    query_fingerprint: "f".repeat(64),
    requested_visibility: null,
    requested_subjects: [],
    note: null,
    void_reason: null,
    decided_by_user_id: null,
    decided_at: null,
    created_at: "2026-10-22T10:00:00Z",
    can_decide: true,
  };
  const REVIEW = {
    version: { ...V2, id: "v3", number: 3 },
    compared_to: 1,
    publisher_name: "Bea Builder",
    bindings: [],
    unchanged: [],
    widens: false,
    problem: null,
  };

  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    useArtifactViewMock.mockReturnValue(STATIC_VIEW);
    useArtifactDataMock.mockReturnValue(NO_DATA);
    reviewMock.mockReturnValue({ data: REVIEW, isLoading: false });
    requestAccess.isSuccess = false;
  });

  function waiting(items = [VERSION_REQUEST]) {
    requestsMock.mockReturnValue({ requests: items, isLoading: false, error: null });
  }

  it("counts what waits on a decider in the strip, and reads only for one", () => {
    waiting([VERSION_REQUEST, { ...VERSION_REQUEST, id: "r2", kind: "access" }]);
    useArtifactMock.mockReturnValue(state(detail({ can_edit: true })));
    render(<ArtifactViewer artifactId="a1" initialVersionId={null} />);

    expect(requestsMock).toHaveBeenCalledWith("a1", false, true);
    expect(screen.getByLabelText("2 requests waiting for you")).toHaveTextContent("2");
  });

  it("words a version notice for a requester and version the server did not name", () => {
    waiting([{ ...VERSION_REQUEST, requester_name: null, version_number: null }]);
    useArtifactMock.mockReturnValue(state(detail({ can_edit: true })));
    render(<ArtifactViewer artifactId="a1" initialVersionId={null} />);

    expect(screen.getByText(/Someone changed what v0 reads/)).toBeVisible();
  });

  it("asks nobody else's list, and draws no badge for a reader", () => {
    requestsMock.mockReturnValue({ requests: [], isLoading: false, error: null });
    useArtifactMock.mockReturnValue(state(detail()));
    render(<ArtifactViewer artifactId="a1" initialVersionId={null} />);

    expect(requestsMock).toHaveBeenCalledWith("a1", false, false);
    expect(screen.queryByLabelText(/requests? waiting/)).toBeNull();
  });

  it("does not count a request the caller may not decide", () => {
    waiting([{ ...VERSION_REQUEST, can_decide: false }]);
    useArtifactMock.mockReturnValue(state(detail({ can_edit: true })));
    render(<ArtifactViewer artifactId="a1" initialVersionId={null} />);

    expect(screen.queryByLabelText(/requests? waiting/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Review data change" })).toBeNull();
  });

  it("opens the Share dialog from the badge, with the requests in it", async () => {
    waiting();
    useArtifactMock.mockReturnValue(state(detail({ can_edit: true })));
    render(<ArtifactViewer artifactId="a1" initialVersionId={null} />);

    await userEvent.click(screen.getByRole("button", { name: /waiting for you/ }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Bea Builder changed what v3 reads")).toBeVisible();
  });

  it("opens the Share dialog at once when a notification linked to the requests", async () => {
    waiting();
    useArtifactMock.mockReturnValue(state(detail({ can_edit: true })));
    render(<ArtifactViewer artifactId="a1" initialVersionId={null} openRequests />);

    expect(await screen.findByRole("dialog")).toBeVisible();
  });

  it("offers the review of a version request under the strip, and closes the dialog to show it", async () => {
    waiting();
    useArtifactMock.mockReturnValue(state(detail({ can_edit: true })));
    render(<ArtifactViewer artifactId="a1" initialVersionId={null} openRequests />);

    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Review data change" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(reviewMock).toHaveBeenCalledWith("a1", "v3", true);
    expect(screen.getByRole("heading", { name: "Review the data change in v3" })).toBeVisible();
  });

  it("reviews from the strip, approves with that version's fingerprint, and closes", async () => {
    waiting();
    const confirmData = mutation();
    useArtifactMock.mockReturnValue(
      state(detail({ can_edit: true }), { confirmData, versions: [V2, V1] }),
    );
    render(<ArtifactViewer artifactId="a1" initialVersionId={null} />);

    expect(
      screen.getByText(
        "Bea Builder changed what v3 reads. The audience keeps seeing the earlier version until you decide.",
      ),
    ).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Review data change" }));
    await userEvent.click(screen.getByRole("button", { name: "Approve" }));

    expect(confirmData.mutateAsync).toHaveBeenCalledWith({
      versionId: "v3",
      fingerprint: "f".repeat(64),
    });
    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: "Review the data change in v3" })).toBeNull(),
    );
  });

  it("declines through the request, and closes once the server took it", async () => {
    waiting();
    useArtifactMock.mockReturnValue(state(detail({ can_edit: true })));
    render(<ArtifactViewer artifactId="a1" initialVersionId={null} />);

    await userEvent.click(screen.getByRole("button", { name: "Review data change" }));
    await userEvent.click(screen.getByRole("button", { name: "Decline" }));
    expect(decline.mutate).toHaveBeenCalledWith("r1", { onSuccess: expect.any(Function) });

    act(() => decline.mutate.mock.calls[0]?.[1].onSuccess());
    expect(screen.queryByRole("heading", { name: "Review the data change in v3" })).toBeNull();
  });

  it("switches the frame to the audience's version for the toggle, and back on close", async () => {
    waiting();
    useArtifactMock.mockReturnValue(state(detail({ can_edit: true }), { versions: [V2, V1] }));
    render(<ArtifactViewer artifactId="a1" initialVersionId={null} />);

    await userEvent.click(screen.getByRole("button", { name: "Review data change" }));
    await userEvent.click(screen.getByRole("switch", { name: "Audience sees now" }));
    await waitFor(() =>
      expect(useArtifactViewMock).toHaveBeenLastCalledWith("a1", "v1", true, false),
    );

    await userEvent.click(screen.getByRole("switch", { name: "Audience sees now" }));
    await waitFor(() => expect(replace).toHaveBeenCalled());

    await userEvent.click(screen.getByRole("switch", { name: "Audience sees now" }));
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: "Review the data change in v3" })).toBeNull(),
    );
  });

  it("closes a review without moving the frame when the audience was never shown", async () => {
    waiting();
    useArtifactMock.mockReturnValue(state(detail({ can_edit: true })));
    render(<ArtifactViewer artifactId="a1" initialVersionId={null} />);

    await userEvent.click(screen.getByRole("button", { name: "Review data change" }));
    await userEvent.click(screen.getByRole("button", { name: "Close" }));

    expect(screen.getByRole("button", { name: "Review data change" })).toBeVisible();
  });

  it("disables the audience toggle when the audience's version is no longer kept", async () => {
    waiting();
    useArtifactMock.mockReturnValue(state(detail({ can_edit: true }), { versions: [V2] }));
    render(<ArtifactViewer artifactId="a1" initialVersionId={null} />);

    await userEvent.click(screen.getByRole("button", { name: "Review data change" }));

    expect(screen.getByRole("switch", { name: "Audience sees now" })).toBeDisabled();
    expect(useArtifactViewMock).not.toHaveBeenCalledWith("a1", "v1", true, false);
  });

  it("drops a review whose request is no longer waiting, and the audience's frame with it", async () => {
    waiting();
    useArtifactMock.mockReturnValue(state(detail({ can_edit: true }), { versions: [V2, V1] }));
    const { rerender } = render(<ArtifactViewer artifactId="a1" initialVersionId={null} />);
    await userEvent.click(screen.getByRole("button", { name: "Review data change" }));
    await userEvent.click(screen.getByRole("switch", { name: "Audience sees now" }));

    waiting([]);
    rerender(<ArtifactViewer artifactId="a1" initialVersionId={null} />);

    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: "Review the data change in v3" })).toBeNull(),
    );
    expect(useArtifactViewMock).toHaveBeenLastCalledWith("a1", null, true, true);
  });

  it("drops a review whose request is gone while the audience is not shown", async () => {
    waiting();
    useArtifactMock.mockReturnValue(state(detail({ can_edit: true })));
    const { rerender } = render(<ArtifactViewer artifactId="a1" initialVersionId={null} />);
    await userEvent.click(screen.getByRole("button", { name: "Review data change" }));

    waiting([]);
    rerender(<ArtifactViewer artifactId="a1" initialVersionId={null} />);

    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: "Review the data change in v3" })).toBeNull(),
    );
  });

  it("takes the requests link out of the address once the dialog has opened", async () => {
    window.history.replaceState(null, "", "/artifacts/a1?requests=open&org=o1");
    waiting();
    useArtifactMock.mockReturnValue(state(detail({ can_edit: true })));
    render(<ArtifactViewer artifactId="a1" initialVersionId={null} openRequests />);

    await screen.findByRole("dialog");
    await waitFor(() =>
      expect(replace).toHaveBeenCalledWith(expect.stringContaining("org=o1"), { scroll: false }),
    );
    expect(replace).not.toHaveBeenCalledWith(
      expect.stringContaining("requests"),
      expect.anything(),
    );
    window.history.replaceState(null, "", "/");
  });

  it("does not open the Share dialog on an archived page", () => {
    waiting();
    useArtifactMock.mockReturnValue(
      state(detail({ can_edit: true, archived_at: "2026-10-01T00:00:00Z" })),
    );
    render(<ArtifactViewer artifactId="a1" initialVersionId={null} openRequests />);

    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("offers Confirm data when approving needs the data confirmed, and confirms what was shown", async () => {
    waiting([{ ...VERSION_REQUEST, kind: "access", version_id: null }]);
    useArtifactDisclosureMock.mockReturnValue({
      isLoading: false,
      data: {
        version: 2,
        fingerprint: "a".repeat(64),
        bindings: {},
        parts: {},
        tables: [],
        visibility: "private",
        people: [],
        groups: [],
        roles: ["owner"],
        problem: null,
      },
      refetch: vi.fn(),
    });
    const confirmData = mutation();
    useArtifactMock.mockReturnValue(
      state(
        livePage({
          can_edit: true,
          consent: {
            version: 2,
            state: "pending",
            fingerprint: "f".repeat(64),
            automatic: false,
            grown: [],
            via: null,
            audience_version: 1,
            shared: true,
            owner_name: "Olga",
            withdrawn_at: null,
            auto_consent: false,
            may_confirm: true,
            may_withdraw: false,
            may_enable_auto_consent: false,
            may_disable_auto_consent: false,
          },
        }),
        { confirmData },
      ),
    );
    render(<ArtifactViewer artifactId="a1" initialVersionId={null} />);
    const dialog = await openShare();

    await userEvent.click(within(dialog).getByRole("button", { name: /^Approve/ }));
    act(() =>
      approve.mutate.mock.calls[0]?.[1].onError(
        new ApiError(409, "x", { error: { code: "CONSENT_REQUIRED", message: "x" } }),
      ),
    );
    // Any other refusal says nothing here.
    act(() =>
      approve.mutate.mock.calls[0]?.[1].onError(
        new ApiError(409, "x", { error: { code: "CONCURRENT_CHANGE", message: "x" } }),
      ),
    );

    expect(within(dialog).getByText("Confirm the page's data before sharing it")).toBeVisible();
    await userEvent.click(within(dialog).getByRole("button", { name: "Confirm data" }));
    expect(useArtifactDisclosureMock).toHaveBeenLastCalledWith("a1", "v2", true);
    const confirmDialog = (await screen.findAllByRole("dialog")).at(-1) as HTMLElement;
    await userEvent.click(within(confirmDialog).getByRole("button", { name: "Confirm data" }));
    expect(confirmData.mutateAsync).toHaveBeenCalledWith({
      versionId: "v2",
      fingerprint: "a".repeat(64),
    });
    // Once confirmed, the notice is gone: there is nothing left to offer.
    await waitFor(() =>
      expect(screen.queryByText("Confirm the page's data before sharing it")).toBeNull(),
    );
  });

  it("offers Confirm data when sharing itself was refused for want of it", async () => {
    waiting([]);
    useArtifactMock.mockReturnValue(
      state(detail({ can_edit: true, consent: consent({ may_confirm: true }) })),
    );
    render(<ArtifactViewer artifactId="a1" initialVersionId={null} />);
    const dialog = await openShare();

    act(() => sharingPanel.mock.lastCall?.[0].onConsentRequired());

    expect(within(dialog).getByText("Confirm the page's data before sharing it")).toBeVisible();
  });

  it("only says so to someone who may not confirm", async () => {
    waiting([]);
    useArtifactMock.mockReturnValue(state(detail({ can_edit: true })));
    render(<ArtifactViewer artifactId="a1" initialVersionId={null} />);
    const dialog = await openShare();

    act(() => sharingPanel.mock.lastCall?.[0].onConsentRequired());

    expect(
      within(dialog).getByText("The page's owner has to confirm its data before it can be shared"),
    ).toBeVisible();
    expect(within(dialog).queryByRole("button", { name: "Confirm data" })).toBeNull();
  });
});
