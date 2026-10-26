import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SharedVisuals } from "./shared-visuals";

vi.mock("@/components/public-config/public-config-provider", () => ({
  usePublicConfig: () => ({ artifactUrl: "https://content.example.com" }),
}));

class VisibleObserver {
  constructor(private readonly report: (entries: { isIntersecting: boolean }[]) => void) {}
  observe() {
    this.report([{ isIntersecting: true }]);
  }
  disconnect() {}
  unobserve() {}
}
beforeEach(() => vi.stubGlobal("IntersectionObserver", VisibleObserver));
afterEach(() => vi.unstubAllGlobals());

describe("SharedVisuals", () => {
  it("draws each finished visual, with nothing to save or ask", async () => {
    render(
      <SharedVisuals
        visuals={[{ id: "v1", title: "Poster", kind: "svg", content: '<svg viewBox="0 0 2 1"/>' }]}
      />,
    );
    expect(await screen.findByText("Poster")).toBeInTheDocument();
    expect(document.querySelector("iframe")).not.toBeNull();
    expect(screen.queryByRole("button", { name: "Save to Apps" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Ask about this" })).toBeNull();
  });
});
