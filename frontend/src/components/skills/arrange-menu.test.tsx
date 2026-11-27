import userEvent from "@testing-library/user-event";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ArrangeMenu, parseArrangement } from "./arrange-menu";

describe("parseArrangement", () => {
  it("reads the arrangement an address names", () => {
    expect(parseArrangement("origin")).toBe("origin");
    expect(parseArrangement("category")).toBe("category");
    expect(parseArrangement("none")).toBe("none");
  });

  it("falls back to by agent for no arrangement or one it does not know", () => {
    expect(parseArrangement(null)).toBe("agent");
    expect(parseArrangement("folder")).toBe("agent");
  });
});

describe("ArrangeMenu", () => {
  it("names the current layout and offers every other", async () => {
    const onChange = vi.fn();
    render(<ArrangeMenu value="agent" onChange={onChange} />);

    await userEvent.click(screen.getByRole("button", { name: "By agent" }));
    expect(screen.getByRole("menuitemradio", { name: "By agent" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(screen.getAllByRole("menuitemradio").map((item) => item.textContent)).toEqual([
      "By agent",
      "By origin",
      "By category",
      "No sections",
    ]);

    await userEvent.click(screen.getByRole("menuitemradio", { name: "By origin" }));
    expect(onChange).toHaveBeenCalledWith("origin");
  });
});
