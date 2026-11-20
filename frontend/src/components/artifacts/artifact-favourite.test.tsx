/**
 * The star on an app's card and in its viewer strip: it shows the caller's
 * state, and a press asks for the other one.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ArtifactCard } from "./artifact-card";
import { ArtifactViewerBar } from "./artifact-viewer-bar";
import type { Artifact, ArtifactDetail } from "@/types/artifact";

const base = {
  id: "a1",
  name: "weekly-report",
  title: "Weekly report",
  visibility: "private" as const,
  owner_user_id: "u1",
  agent_id: "ag1",
  environment_id: null,
  environment_name: null,
  public_url: null,
  live: false,
  published_at: "2026-09-22T10:00:00Z",
  current_version: null,
  archived_at: null,
  created_at: "2026-09-01T10:00:00Z",
  updated_at: null,
};

describe("the star on a card", () => {
  it("is drawn only when the page passes one, and asks for the other state", async () => {
    const onToggle = vi.fn();
    const artifact: Artifact = { ...base, is_favourite: false };
    const { rerender } = render(<ArtifactCard artifact={artifact} />);
    expect(screen.queryByRole("button", { name: "Add Weekly report to favourites" })).toBeNull();

    rerender(<ArtifactCard artifact={artifact} favourite={{ on: false, onToggle }} />);
    const star = screen.getByRole("button", { name: "Add Weekly report to favourites" });
    expect(star).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(star);
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it("names the removal when the app is starred", () => {
    render(
      <ArtifactCard
        artifact={{ ...base, is_favourite: true }}
        favourite={{ on: true, onToggle: vi.fn() }}
      />,
    );
    expect(
      screen.getByRole("button", { name: "Remove Weekly report from favourites" }),
    ).toHaveAttribute("aria-pressed", "true");
  });
});

describe("the star in the viewer strip", () => {
  const detail = { ...base, is_favourite: false } as unknown as ArtifactDetail;

  it("is absent until the page is loaded", () => {
    render(<ArtifactViewerBar artifact={null} favourite={{ on: false, onToggle: vi.fn() }} />);
    expect(screen.queryByRole("button", { name: /favourites/ })).toBeNull();
  });

  it("asks for the other state when pressed, and is disabled while busy", async () => {
    const onToggle = vi.fn();
    const { rerender } = render(
      <ArtifactViewerBar artifact={detail} favourite={{ on: false, onToggle }} />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Add Weekly report to favourites" }));
    expect(onToggle).toHaveBeenCalledTimes(1);

    rerender(
      <ArtifactViewerBar artifact={detail} favourite={{ on: true, busy: true, onToggle }} />,
    );
    expect(
      screen.getByRole("button", { name: "Remove Weekly report from favourites" }),
    ).toBeDisabled();
  });
});
