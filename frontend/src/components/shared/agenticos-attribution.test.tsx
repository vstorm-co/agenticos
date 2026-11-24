import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AgenticosAttribution } from "./agenticos-attribution";
import { LOGO_DATA_URI } from "@/lib/logo.generated";

describe("shared AgenticOS attribution", () => {
  it("shows the canonical logo and a GitHub link by default", () => {
    const { container } = render(<AgenticosAttribution />);
    expect(screen.getByText("AgenticOS")).toBeVisible();
    expect(container.querySelector("img")).toHaveAttribute("src", LOGO_DATA_URI);
    const link = screen.getByRole("link");
    expect(link).toHaveAttribute("href", "https://github.com/vstorm-co/agenticos");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(link).toHaveAttribute("referrerpolicy", "no-referrer");
  });

  it("removes both branding and link when the organization opts out", () => {
    const { container } = render(<AgenticosAttribution visible={false} />);
    expect(container).toBeEmptyDOMElement();
  });
});
