import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { UnsavedChangesGuard } from "@/components/layout/unsaved-changes-guard";
import { ApiError } from "@/lib/api-error";
import { useUnsavedChangesStore } from "@/stores/unsaved-changes-store";
import type { Dataset } from "@/types/datasets";
import { EditDatasetDialog } from "./edit-dataset-dialog";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
import { toast } from "sonner";

const DATASET = { id: "d1", name: "refunds", description: "Returns" } as Dataset;

function mount(mutateAsync = vi.fn().mockResolvedValue({}), dataset: Dataset = DATASET) {
  const onOpenChange = vi.fn();
  render(
    <>
      <EditDatasetDialog
        dataset={dataset}
        onOpenChange={onOpenChange}
        update={{ mutateAsync, isPending: false }}
      />
      <UnsavedChangesGuard />
    </>,
  );
  return { onOpenChange, mutateAsync };
}

describe("EditDatasetDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useUnsavedChangesStore.setState({ sources: {}, prompt: null, saving: false });
  });

  it("closes at once unchanged, and asks first with a change, saving from the question", async () => {
    const { onOpenChange, mutateAsync } = mount();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
    onOpenChange.mockClear();

    await userEvent.type(screen.getByLabelText(/Name/), "-2026");
    await userEvent.keyboard("{Escape}");
    expect(screen.getByRole("dialog", { name: "You have unsaved changes" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(mutateAsync).toHaveBeenCalledWith(expect.objectContaining({ name: "refunds-2026" }));
  });

  it("offers no Save on the way out while the name is empty, and discards on request", async () => {
    const { onOpenChange, mutateAsync } = mount();
    await userEvent.clear(screen.getByLabelText(/Name/));
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Discard" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(mutateAsync).not.toHaveBeenCalled();
  });

  it("starts from the dataset's own name and description, and saves what was changed", async () => {
    const { onOpenChange, mutateAsync } = mount();
    const name = screen.getByLabelText(/^Name/);
    expect(name).toHaveValue("refunds");
    await userEvent.clear(name);
    await userEvent.type(name, " refund questions ");
    await userEvent.clear(screen.getByLabelText("Description"));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(mutateAsync).toHaveBeenCalledWith({ name: "refund questions", description: null });
    expect(toast.success).toHaveBeenCalledWith("Saved");
  });

  it("keeps a description that was written, and needs a name to save", async () => {
    const { mutateAsync } = mount();
    await userEvent.clear(screen.getByLabelText(/^Name/));
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/^Name/), "refunds");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(mutateAsync).toHaveBeenCalledWith({ name: "refunds", description: "Returns" }),
    );
  });

  it("says a taken name under the name and stays open", async () => {
    const taken = "A dataset named 'returns' already exists.";
    const { onOpenChange } = mount(
      vi.fn().mockRejectedValue(
        new ApiError(409, taken, {
          error: { code: "ALREADY_EXISTS", message: taken, details: { name: "returns" } },
        }),
      ),
    );
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText(taken)).toBeInTheDocument();
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });

  it("refuses with a toast what names no field", async () => {
    mount(vi.fn().mockRejectedValue(new Error("down")));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
  });

  it("opens an undescribed dataset with an empty description", () => {
    mount(undefined, { ...DATASET, description: null });
    expect(screen.getByLabelText("Description")).toHaveValue("");
  });
  it("changes the split only for future questions and refuses invalid percentages", async () => {
    const { mutateAsync } = mount();
    expect(screen.getByText(/existing questions keep their part/)).toBeInTheDocument();
    const share = screen.getByLabelText("Holdout share for new questions (%)");
    await userEvent.clear(share);
    await userEvent.type(share, "101");
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(mutateAsync).not.toHaveBeenCalled();
    await userEvent.clear(share);
    await userEvent.type(share, "33.3");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(mutateAsync).toHaveBeenCalledWith({
        name: "refunds",
        description: "Returns",
        improvement_holdout_share: "0.333",
      }),
    );
  });
});
