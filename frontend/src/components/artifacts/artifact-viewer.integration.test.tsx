import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ArtifactViewer } from "./artifact-viewer";
import { ApiError } from "@/lib/api-error";
import type { ArtifactDetail as ArtifactDetailData } from "@/types/artifact";

/**
 * What a reader and a manager each get on one artifact's page.
 *
 * The page is the whole window and who reaches it lives behind Share. `can_edit`
 * is the server's answer, grants included, and it is the only thing that decides
 * whether a control that changes the artifact is drawn - a reader sees the page
 * and, behind Share, who else can, and has nothing to press.
 */

const useArtifactMock = vi.fn();
const push = vi.fn();
const sharingPanel = vi.fn();

vi.mock("@/hooks/use-artifacts", () => ({
  useArtifact: (...args: unknown[]) => useArtifactMock(...args),
  useArtifactView: () => ({ isLoading: false, data: { url: "https://api/c/t" } }),
}));
vi.mock("@/lib/locale-navigation", () => ({ useRouter: () => ({ push }) }));
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
    public_url: null,
    published_at: "2026-09-22T10:00:00Z",
    current_version: null,
    created_at: "2026-09-01T10:00:00Z",
    updated_at: null,
    can_edit: false,
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
    remove: mutation(),
    ...overrides,
  };
}

async function openShare() {
  await userEvent.click(screen.getByRole("button", { name: "Share" }));
  return screen.findByRole("dialog");
}

describe("ArtifactViewer", () => {
  beforeEach(() => vi.clearAllMocks());

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

  it("waits for the artifact before drawing anything", () => {
    useArtifactMock.mockReturnValue(state(null, { isLoading: true }));
    render(<ArtifactViewer artifactId="a1" initialVersionId={null} />);
    expect(screen.queryByText("This artifact is not available")).toBeNull();
    expect(screen.queryByRole("button", { name: "Share" })).toBeNull();
  });
});
