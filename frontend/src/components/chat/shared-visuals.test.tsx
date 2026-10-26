import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SharedVisuals } from "./shared-visuals";

vi.mock("@/components/public-config/public-config-provider", () => ({
  usePublicConfig: () => ({ artifactUrl: "https://content.example.com" }),
}));

afterEach(() => vi.unstubAllGlobals());

describe("SharedVisuals", () => {
  it("draws each finished visual, with nothing to save or ask", () => {
    let reveal = () => {};
    class VisibleObserver extends IntersectionObserver {
      constructor(
        private readonly notify: IntersectionObserverCallback,
        options?: IntersectionObserverInit,
      ) {
        super(notify, options);
      }
      observe = (target: Element) => {
        reveal = () => {
          const rect = target.getBoundingClientRect();
          this.notify(
            [
              {
                target,
                isIntersecting: true,
                intersectionRatio: 1,
                boundingClientRect: rect,
                intersectionRect: rect,
                rootBounds: null,
                time: 0,
              },
            ],
            this,
          );
        };
      };
    }
    vi.stubGlobal("IntersectionObserver", VisibleObserver);
    render(
      <SharedVisuals
        visuals={[{ id: "v1", title: "Poster", kind: "svg", content: '<svg viewBox="0 0 2 1"/>' }]}
      />,
    );
    expect(screen.getByText("Poster")).toBeInTheDocument();
    expect(document.querySelector("iframe")).toBeNull();
    act(() => reveal());
    expect(document.querySelector("iframe")).not.toBeNull();
    expect(screen.queryByRole("button", { name: "Save to Apps" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Ask about this" })).toBeNull();
  });
});
