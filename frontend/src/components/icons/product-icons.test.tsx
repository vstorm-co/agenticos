import { createRef } from "react";
import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import * as icons from "./product-icons";

describe("product icon contract", () => {
  it.each(Object.entries(icons))(
    "%s supports accessible names, refs and explicit sizing",
    (_, Icon) => {
      const ref = createRef<SVGSVGElement>();
      const { getByRole } = render(
        <Icon ref={ref} role="img" aria-label="Landmark" size={18} strokeWidth={1.6} />,
      );
      expect(ref.current).toBe(getByRole("img", { name: "Landmark" }));
      expect(ref.current).toHaveAttribute("width", "18");
      expect(ref.current).toHaveAttribute("stroke-width", "1.6");
    },
  );

  it("renders the complete family without React child-key warnings", () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => undefined);
    try {
      render(
        <>
          {Object.entries(icons).map(([name, Icon]) => (
            <Icon key={name} aria-hidden />
          ))}
        </>,
      );
      expect(error).not.toHaveBeenCalled();
    } finally {
      error.mockRestore();
    }
  });
});
