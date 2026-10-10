import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { LiveUpdates } from "./live-updates";

const useLiveUpdates = vi.hoisted(() => vi.fn());
vi.mock("@/hooks/use-live-updates", () => ({ useLiveUpdates }));

describe("LiveUpdates", () => {
  it("holds the socket and draws nothing", () => {
    const { container } = render(<LiveUpdates />);

    expect(useLiveUpdates).toHaveBeenCalled();
    expect(container).toBeEmptyDOMElement();
  });
});
