import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { checkAgent } from "@/test-utils/skill-checks";
import { SetUpGrading } from "./set-up-grading";

describe("SetUpGrading", () => {
  it("links each dataset the agents were to be asked once, and names none it may not see", () => {
    const hidden = { ...checkAgent().stages[0]!, dataset_id: "d-9", dataset_name: null };
    render(
      <SetUpGrading
        agents={[checkAgent({ name: "A" }), checkAgent({ name: "B", stages: [hidden] })]}
      />,
    );

    const links = screen.getAllByRole("link");
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "/datasets/d-1?tab=grading",
      "/datasets/d-2?tab=grading",
    ]);
    expect(screen.getByText("Set up grading on Skill set")).toBeInTheDocument();
  });

  it("draws nothing without a dataset to link", () => {
    const { container } = render(<SetUpGrading agents={[checkAgent({ stages: [] })]} />);

    expect(container).toBeEmptyDOMElement();
  });
});
