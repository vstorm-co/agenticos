import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ProjectAvatar } from "./project-avatar";

describe("project identity", () => {
  it("keeps the same initial at sidebar, picker and page sizes", () => {
    render(
      <>
        {(["xs", "sm", "md", "lg"] as const).map((size) => (
          <ProjectAvatar key={size} name="  Fall launch " size={size} />
        ))}
      </>,
    );
    const marks = screen.getAllByText("F");
    expect(marks).toHaveLength(4);
    for (const mark of marks) expect(mark).toHaveAttribute("aria-hidden", "true");
  });

  it("keeps non-ASCII project initials intact", () => {
    render(
      <>
        <ProjectAvatar name="łódź" />
        <ProjectAvatar name="🚀 Launch" />
      </>,
    );
    expect(screen.getByText("Ł")).toBeInTheDocument();
    expect(screen.getByText("🚀")).toBeInTheDocument();
  });

  it("leaves a neutral placeholder when the name is empty", () => {
    render(<ProjectAvatar name=" " />);
    expect(screen.getByText("·")).toBeInTheDocument();
  });
});
