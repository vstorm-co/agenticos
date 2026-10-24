import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ImprovementMeasurement } from "./improvement-measurement";

describe("ImprovementMeasurement", () => {
  it("explains the blind verdict, excluded copies and missing gradable questions", () => {
    render(
      <ImprovementMeasurement
        measurement={{
          train_case_ids: ["t1", "t2"],
          holdout_case_ids: ["h1", "h2", "h3"],
          excluded_case_ids: ["copy"],
          gradable_holdout: 2,
          minimum_holdout: 5,
        }}
      />,
    );
    expect(screen.getByText("Questions used to write the changes")).toBeInTheDocument();
    expect(screen.getByText("Held-out questions")).toBeInTheDocument();
    expect(screen.getByText(/repeat training questions or proposal evidence/)).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Add 3 more gradable held-out questions");
  });

  it("does not ask for more cases when the minimum is satisfied", () => {
    render(
      <ImprovementMeasurement
        measurement={{
          train_case_ids: [],
          holdout_case_ids: ["1", "2", "3", "4", "5"],
          excluded_case_ids: [],
          gradable_holdout: 5,
          minimum_holdout: 5,
        }}
      />,
    );
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByText(/excluded from the verdict/)).not.toBeInTheDocument();
  });
});
