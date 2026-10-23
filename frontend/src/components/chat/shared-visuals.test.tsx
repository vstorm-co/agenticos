import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SharedVisuals } from "./shared-visuals";

vi.mock("@/components/public-config/public-config-provider", () => ({
  usePublicConfig: () => ({ artifactUrl: "https://content.example.com" }),
}));

describe("SharedVisuals", () => {
  it("draws each finished visual, with nothing to save or ask", () => {
    render(
      <SharedVisuals
        visuals={[{ id: "v1", title: "Poster", kind: "svg", content: '<svg viewBox="0 0 2 1"/>' }]}
      />,
    );
    expect(screen.getByText("Poster")).toBeInTheDocument();
    expect(document.querySelector("iframe")).not.toBeNull();
    expect(screen.queryByRole("button", { name: "Save to Apps" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Ask about this" })).toBeNull();
  });
});
