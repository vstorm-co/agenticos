import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DatasetTargetFields } from "./dataset-target-fields";

describe("DatasetTargetFields", () => {
  it("points at creating a dataset when there is none and none is made here", () => {
    render(
      <DatasetTargetFields
        editable={[]}
        isLoading={false}
        datasetId=""
        onDatasetChange={vi.fn()}
        idPrefix="t"
      />,
    );

    expect(screen.getByRole("link", { name: "Create one" })).toHaveAttribute("href", "/datasets");
  });
});
