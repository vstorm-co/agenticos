import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { GapToDatasetDialog } from "./gap-to-dataset-dialog";

const state = vi.hoisted(() => ({
  datasets: [] as { id: string; name: string; can_edit: boolean }[],
  isLoading: false,
  add: vi.fn(),
}));
vi.mock("@/hooks/use-datasets", () => ({
  useDatasets: () => ({ datasets: state.datasets, isLoading: state.isLoading }),
}));
vi.mock("@/hooks/use-knowledge-gaps", () => ({
  useAddKnowledgeGapToDataset: () => ({ mutate: state.add, isPending: false }),
}));

describe("GapToDatasetDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    state.isLoading = false;
    state.datasets = [
      { id: "d1", name: "refunds", can_edit: true },
      { id: "d2", name: "read only", can_edit: false },
      { id: "d3", name: "leave", can_edit: true },
    ];
  });

  it("adds the topic to the first dataset the caller may change, and closes once it is in", async () => {
    const onClose = vi.fn();
    state.add.mockImplementation((_vars, options: { onSuccess: () => void }) =>
      options.onSuccess(),
    );
    render(<GapToDatasetDialog topicId="t1" onClose={onClose} />);
    await userEvent.click(screen.getByRole("combobox", { name: "Dataset" }));
    expect(screen.queryByRole("option", { name: "read only" })).toBeNull();
    await userEvent.keyboard("{Escape}");
    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(state.add).toHaveBeenCalledWith(
      { topicId: "t1", datasetId: "d1", name: "refunds" },
      expect.objectContaining({ onSuccess: onClose }),
    );
    expect(onClose).toHaveBeenCalled();
  });

  it("adds to the dataset chosen", async () => {
    render(<GapToDatasetDialog topicId="t1" onClose={vi.fn()} />);
    await userEvent.click(screen.getByRole("combobox", { name: "Dataset" }));
    await userEvent.click(screen.getByRole("option", { name: "leave" }));
    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(state.add).toHaveBeenCalledWith(
      { topicId: "t1", datasetId: "d3", name: "leave" },
      expect.anything(),
    );
  });

  it("points at creating a dataset when there is none to add to", async () => {
    const onClose = vi.fn();
    state.datasets = [{ id: "d2", name: "read only", can_edit: false }];
    render(<GapToDatasetDialog topicId="t1" onClose={onClose} />);
    expect(screen.getByRole("link", { name: "Create one" })).toHaveAttribute("href", "/datasets");
    expect(screen.getByRole("button", { name: "Add" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalled();
  });

  it("closes on Escape", async () => {
    const onClose = vi.fn();
    render(<GapToDatasetDialog topicId="t1" onClose={onClose} />);
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();
  });
});
