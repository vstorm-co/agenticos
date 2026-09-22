import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ArtifactCard } from "./artifact-card";
import { ARTIFACT_SANDBOX, ArtifactFrame, ArtifactFrameView } from "./artifact-frame";
import { PublicArtifact } from "./public-artifact";
import { PublicLinkCard } from "./public-link-card";
import { VersionPicker } from "./version-picker";
import type { Artifact, ArtifactVersion } from "@/types/artifact";

const useArtifactViewMock = vi.fn();
vi.mock("@/hooks/use-artifacts", () => ({
  useArtifactView: (...args: unknown[]) => useArtifactViewMock(...args),
}));

function version(number: number, overrides: Partial<ArtifactVersion> = {}): ArtifactVersion {
  return {
    id: `v${number}`,
    number,
    media_type: "text/html",
    size_bytes: 10,
    run_id: null,
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
    public_url: null,
    published_at: "2026-09-22T10:00:00Z",
    current_version: version(3),
    created_at: "2026-09-01T10:00:00Z",
    updated_at: null,
    ...overrides,
  };
}

describe("the frame", () => {
  beforeEach(() => vi.clearAllMocks());

  it("never grants the page this console's origin", () => {
    render(
      <ArtifactFrameView url="https://api.example/api/v1/artifact-content/t" title="Report" />,
    );
    const frame = screen.getByTitle("Report");
    expect(frame.getAttribute("sandbox")).toBe(ARTIFACT_SANDBOX);
    expect(ARTIFACT_SANDBOX).not.toContain("allow-same-origin");
    expect(ARTIFACT_SANDBOX).not.toContain("allow-top-navigation");
    expect(frame.getAttribute("referrerpolicy")).toBe("no-referrer");
    expect(frame.getAttribute("src")).toBe("https://api.example/api/v1/artifact-content/t");
  });

  it("loads the version asked for from a fresh address", () => {
    useArtifactViewMock.mockReturnValue({ isLoading: false, data: { url: "https://x/c/t" } });
    render(<ArtifactFrame artifactId="a1" versionId="v2" title="Report" />);
    expect(useArtifactViewMock).toHaveBeenCalledWith("a1", "v2", true);
    expect(screen.getByTitle("Report").getAttribute("src")).toBe("https://x/c/t");
  });

  it("says a pruned or withdrawn version is not available", () => {
    useArtifactViewMock.mockReturnValue({ isLoading: false, data: undefined });
    render(<ArtifactFrame artifactId="a1" versionId="gone" title="Report" />);
    expect(screen.getByText("This version is not available")).toBeInTheDocument();
    expect(screen.queryByTitle("Report")).toBeNull();
  });

  it("shows a skeleton while the address is minted", () => {
    useArtifactViewMock.mockReturnValue({ isLoading: true, data: undefined });
    const { container } = render(<ArtifactFrame artifactId="a1" versionId={null} title="R" />);
    expect(container.querySelector("iframe")).toBeNull();
  });
});

describe("the list card", () => {
  it("says who else can read it", () => {
    render(
      <ArtifactCard artifact={artifact({ visibility: "org", public_url: "https://x/a/k" })} />,
    );
    expect(screen.getByText("Whole organization")).toBeInTheDocument();
    expect(screen.getByText("Public link")).toBeInTheDocument();
    expect(screen.getByRole("link").getAttribute("href")).toBe("/artifacts/a1");
    expect(screen.getByText(/Version 3/)).toBeInTheDocument();
  });

  it("shows no reach badge for a private page", () => {
    render(<ArtifactCard artifact={artifact({ current_version: null })} />);
    expect(screen.queryByText("Whole organization")).toBeNull();
    expect(screen.queryByText("Public link")).toBeNull();
    expect(screen.getByText(/Version 0/)).toBeInTheDocument();
  });
});

describe("the public link card", () => {
  it("offers a manager a link to create when there is none", async () => {
    const onEnable = vi.fn();
    render(
      <PublicLinkCard
        publicUrl={null}
        canManage
        busy={false}
        onEnable={onEnable}
        onDisable={vi.fn()}
      />,
    );
    expect(
      screen.getByText("Only people this artifact is shared with can open it."),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Create a public link" }));
    expect(onEnable).toHaveBeenCalled();
  });

  it("lets a manager replace or turn off a live link", async () => {
    const onEnable = vi.fn();
    const onDisable = vi.fn();
    render(
      <PublicLinkCard
        publicUrl="https://console.example/a/key"
        canManage
        busy={false}
        onEnable={onEnable}
        onDisable={onDisable}
      />,
    );
    expect(screen.getByLabelText("Public link")).toHaveValue("https://console.example/a/key");
    await userEvent.click(screen.getByRole("button", { name: "Replace the link" }));
    await userEvent.click(screen.getByRole("button", { name: "Turn off" }));
    expect(onEnable).toHaveBeenCalled();
    expect(onDisable).toHaveBeenCalled();
  });

  it("shows a reader the link and nothing to press", () => {
    render(
      <PublicLinkCard
        publicUrl="https://console.example/a/key"
        canManage={false}
        busy={false}
        onEnable={vi.fn()}
        onDisable={vi.fn()}
      />,
    );
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
    await userEvent.click(screen.getByRole("combobox", { name: "Version" }));
    await userEvent.click(screen.getByRole("option", { name: /Version 1/ }));
    expect(onChange).toHaveBeenLastCalledWith("v1");

    rerender(<VersionPicker versions={[version(2), version(1)]} value="v1" onChange={onChange} />);
    await userEvent.click(screen.getByRole("combobox", { name: "Version" }));
    await userEvent.click(screen.getByRole("option", { name: "Latest version" }));
    expect(onChange).toHaveBeenLastCalledWith(null);
  });
});

describe("the public page", () => {
  it("shows the page and when it was published, and nothing about who made it", () => {
    render(
      <PublicArtifact
        artifact={{
          title: "Weekly report",
          published_at: "2026-09-22T10:00:00Z",
          view: { url: "https://api/c/t", expires_at: "", version: version(3) },
        }}
      />,
    );
    expect(screen.getByRole("heading", { name: "Weekly report" })).toBeInTheDocument();
    expect(screen.getByText(/Updated/)).toBeInTheDocument();
    expect(screen.getByTitle("Weekly report").getAttribute("src")).toBe("https://api/c/t");
  });
});
