import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LinkFavicon } from "./link-favicon";

describe("site icons", () => {
  it("falls back without losing the link and retries when the site changes", () => {
    const { container, rerender } = render(<LinkFavicon url="https://first.example/article" />);
    const first = container.querySelector("img");
    if (!first) throw new Error("missing favicon request");
    expect(first).toHaveAttribute("src", "/api/link-icon?host=first.example");
    fireEvent.error(first);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector(".lucide-globe")).toBeInTheDocument();
    rerender(<LinkFavicon url="https://second.example/path?private=value" />);
    expect(container.querySelector("img")).toHaveAttribute(
      "src",
      "/api/link-icon?host=second.example",
    );
  });

  it.each([
    "not an address",
    "mailto:hello@example.com",
    "data:text/plain,hello",
    "javascript:alert(1)",
  ])("does not request an icon for %s", (url) => {
    const { container } = render(<LinkFavicon url={url} />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector(".lucide-globe")).toBeInTheDocument();
  });

  it("keeps known brands local", () => {
    const { container } = render(<LinkFavicon url="https://github.com/example/repo" />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector(".lucide-globe")).toBeNull();
  });
});
