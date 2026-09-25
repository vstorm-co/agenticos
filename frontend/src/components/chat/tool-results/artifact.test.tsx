import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PublishedArtifactResult, parsePublishedArtifact } from "./artifact";

const PUBLISHED = {
  kind: "artifact",
  artifact_id: "a1",
  version_id: "v 3",
  version: 3,
  name: "weekly-report",
  title: "Weekly report",
  url: "https://console.example/artifacts/a1",
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
    expect(screen.getByRole("link")).toHaveAttribute("href", "/artifacts/a1?version=v%203");
    expect(screen.getByText("Version 3 · open the page")).toBeInTheDocument();
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
