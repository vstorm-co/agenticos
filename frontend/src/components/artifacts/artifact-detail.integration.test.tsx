import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ArtifactDetail } from "./artifact-detail";
import { ApiError } from "@/lib/api-error";
import type { ArtifactDetail as ArtifactDetailData } from "@/types/artifact";

/**
 * What a reader and a manager each get on one artifact's page.
 *
 * `can_edit` is the server's answer, grants included, and it is the only thing
 * that decides whether a control that changes the artifact is drawn - a reader
 * sees the page, its versions and who else can, and has nothing to press.
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

describe("ArtifactDetail", () => {
  beforeEach(() => vi.clearAllMocks());

  it("gives a reader the page and nothing that changes it", () => {
    useArtifactMock.mockReturnValue(state(detail()));
    render(<ArtifactDetail artifactId="a1" initialVersionId={null} />);

    expect(screen.getByTitle("Weekly report").getAttribute("src")).toBe("https://api/c/t");
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Create a public link" })).toBeNull();
    expect(sharingPanel).toHaveBeenCalledWith(
      expect.objectContaining({ resourceType: "artifact", canManage: false }),
    );
  });

  it("lets a manager turn the public link on", async () => {
    const hooks = state(detail({ can_edit: true }));
    useArtifactMock.mockReturnValue(hooks);
    render(<ArtifactDetail artifactId="a1" initialVersionId={null} />);

    await userEvent.click(screen.getByRole("button", { name: "Create a public link" }));
    expect(hooks.enablePublicLink.mutate).toHaveBeenCalled();
    expect(sharingPanel).toHaveBeenCalledWith(expect.objectContaining({ canManage: true }));
  });

  it("turns a live link off", async () => {
    const hooks = state(detail({ can_edit: true, public_url: "https://c/a/k" }));
    useArtifactMock.mockReturnValue(hooks);
    render(<ArtifactDetail artifactId="a1" initialVersionId={null} />);

    await userEvent.click(screen.getByRole("button", { name: "Turn off" }));
    expect(hooks.disablePublicLink.mutate).toHaveBeenCalled();
  });

  it("deletes after a confirmation and goes back to the list", async () => {
    const hooks = state(detail({ can_edit: true }));
    useArtifactMock.mockReturnValue(hooks);
    render(<ArtifactDetail artifactId="a1" initialVersionId={null} />);

    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/artifacts"));
    expect(hooks.remove.mutateAsync).toHaveBeenCalled();
  });

  it("says an artifact that is gone or no longer shared is not available", () => {
    useArtifactMock.mockReturnValue(
      state(null, { error: new ApiError(404, "Artifact not found") }),
    );
    render(<ArtifactDetail artifactId="gone" initialVersionId={null} />);
    expect(screen.getByText("This artifact is not available")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
  });

  it("offers a retry for a failed request rather than calling the artifact gone", async () => {
    const hooks = state(null, { error: new ApiError(503, "Service unavailable") });
    useArtifactMock.mockReturnValue(hooks);
    render(<ArtifactDetail artifactId="a1" initialVersionId={null} />);

    expect(screen.queryByText("This artifact is not available")).toBeNull();
    expect(screen.getByText("This artifact could not be loaded")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(hooks.refetch).toHaveBeenCalled();
  });

  it("waits for the artifact before drawing anything", () => {
    useArtifactMock.mockReturnValue(state(null, { isLoading: true }));
    render(<ArtifactDetail artifactId="a1" initialVersionId={null} />);
    expect(screen.queryByText("This artifact is not available")).toBeNull();
  });
});
