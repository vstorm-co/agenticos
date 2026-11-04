import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { QrCode } from "./qr-code";

describe("QrCode", () => {
  it("draws the value as dark modules on a light ground, named for a screen reader", () => {
    render(<QrCode value="agenticos://pair?code=x" label="A pairing code" size={120} />);
    const svg = screen.getByRole("img", { name: "A pairing code" });
    expect(svg).toHaveAttribute("width", "120");
    expect(svg.querySelector("path")?.getAttribute("d")).toMatch(/^M\d+ \d+h1v1h-1z/);
  });
});
