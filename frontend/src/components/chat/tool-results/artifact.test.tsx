import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PublishedArtifactResult, parsePublishedArtifact, publishedApps } from "./artifact";

vi.mock("@/components/artifacts/artifact-thumbnail", () => ({
  ArtifactThumbnail: ({ artifactId, versionId }: { artifactId: string; versionId: string }) => (
    <span data-testid="thumbnail">{`${artifactId}@${versionId}`}</span>
  ),
}));

const PUBLISHED = {
  kind: "artifact",
  artifact_id: "a1",
  version_id: "v 3",
  version: 3,
  name: "weekly-report",
  title: "Weekly report",
  url: "https://console.example/apps/a1",
  created: false,
  unchanged: false,
  visibility: "private",
  public: false,
};

describe("parsePublishedArtifact", () => {
  it("reads what the tool returns", () => {
    expect(parsePublishedArtifact(JSON.stringify(PUBLISHED))).toEqual({
      artifactId: "a1",
      versionId: "v 3",
      version: 3,
      title: "Weekly report",
      unchanged: false,
    });
  });

  it("answers null for a refusal, another tool's JSON, and a payload missing its ids", () => {
    expect(parsePublishedArtifact("Reading 'x.html' was refused")).toBeNull();
    expect(parsePublishedArtifact(JSON.stringify({ kind: "generated_image" }))).toBeNull();
    expect(
      parsePublishedArtifact(JSON.stringify({ kind: "artifact", artifact_id: "a1" })),
    ).toBeNull();
    expect(parsePublishedArtifact("null")).toBeNull();
  });

  it("falls back to an empty title rather than the word undefined", () => {
    const { title: _title, ...untitled } = PUBLISHED;
    expect(parsePublishedArtifact(JSON.stringify(untitled))?.title).toBe("");
  });
});

describe("PublishedArtifactResult", () => {
  it("links to the version this run published", () => {
    render(
      <PublishedArtifactResult
        data={{
          artifactId: "a1",
          versionId: "v 3",
          version: 3,
          title: "Weekly report",
          unchanged: false,
        }}
      />,
    );
    const link = screen.getByRole("link");
    expect(link).toHaveAttribute("href", "/apps/a1?version=v%203");
    // A new tab, so the conversation stays where it was.
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.getByText("Version 3 · open the page")).toBeInTheDocument();
    // The preview is of that version too, not of whatever the link shows today.
    expect(screen.getByTestId("thumbnail")).toHaveTextContent("a1@v 3");
  });

  it("says when nothing changed and no version was added", () => {
    render(
      <PublishedArtifactResult
        data={{
          artifactId: "a1",
          versionId: "v3",
          version: 3,
          title: "Weekly report",
          unchanged: true,
        }}
      />,
    );
    expect(screen.getByText("Unchanged, still version 3 · open the page")).toBeInTheDocument();
  });
});

describe("the apps a turn published", () => {
  const published = (artifact: string, version: number) => ({
    id: `${artifact}-${version}`,
    name: "publish_artifact",
    args: {},
    status: "completed" as const,
    result: JSON.stringify({
      kind: "artifact",
      artifact_id: artifact,
      version_id: `${artifact}-v${version}`,
      version,
      title: `App ${artifact}`,
    }),
  });

  it("keeps one card per app, at the last version the turn wrote", () => {
    const apps = publishedApps([
      published("a", 1),
      published("b", 1),
      published("a", 2),
      { id: "x", name: "publish_artifact", args: {}, status: "completed", result: "refused" },
      { id: "y", name: "web_search", args: {}, status: "completed", result: "{}" },
      { id: "z", name: "publish_artifact", args: {}, status: "running" },
    ]);

    expect(apps.map((app) => [app.artifactId, app.version])).toEqual([
      ["b", 1],
      ["a", 2],
    ]);
  });
});
