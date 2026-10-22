import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Perm } from "@/types/permissions";
import { AddToDatasetButton } from "./add-to-dataset-button";
import { AddToDatasetDialog } from "./add-to-dataset-dialog";

const state = vi.hoisted(() => ({
  granted: [] as string[],
  datasets: [] as { id: string; name: string; can_edit: boolean }[],
  isLoading: false,
  total: 0,
  lastQuery: undefined as unknown,
  add: vi.fn(),
  create: vi.fn(),
  asked: null as string | null,
  push: vi.fn(),
}));
vi.mock("next/navigation", async (original) => ({
  ...(await original<typeof import("next/navigation")>()),
  useRouter: () => ({ push: state.push }),
  useSearchParams: () => new URLSearchParams(state.asked === null ? "" : `dataset=${state.asked}`),
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: (perm: string) => state.granted.includes(perm) }),
}));
vi.mock("@/hooks/use-datasets", () => ({
  // The server's `editable` filter, as the listing applies it.
  useDatasets: (query: { editable?: boolean }) => {
    state.lastQuery = query;
    const rows = query.editable
      ? state.datasets.filter((dataset) => dataset.can_edit)
      : state.datasets;
    return {
      datasets: rows,
      total: state.total || rows.length,
      isLoading: state.isLoading,
      create: { mutateAsync: state.create, isPending: false },
    };
  },
  useAddToDataset: () => ({ mutateAsync: state.add, isPending: false }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
import { toast } from "sonner";

const open = () => userEvent.click(screen.getByRole("button", { name: "Add to dataset" }));

describe("Add to dataset", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    state.granted = [Perm.datasetsEdit];
    state.datasets = [
      { id: "d1", name: "refunds", can_edit: true },
      { id: "d2", name: "read only", can_edit: false },
      { id: "d3", name: "returns", can_edit: true },
    ];
    state.isLoading = false;
    state.total = 0;
    state.asked = null;
  });

  it("is not offered to somebody who edits no dataset", () => {
    state.granted = [Perm.datasetsView];
    state.datasets = [{ id: "d2", name: "read only", can_edit: false }];
    render(<AddToDatasetButton messageId="m1" ratedDown />);
    expect(screen.queryByRole("button", { name: "Add to dataset" })).toBeNull();
  });

  it("is offered to somebody an edit grant lets add to one dataset", async () => {
    state.granted = [Perm.datasetsView];
    state.add.mockResolvedValue({});
    render(<AddToDatasetButton messageId="m1" ratedDown />);
    await open();
    expect(screen.getByText(/the comment left with a thumbs-down/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(state.add).toHaveBeenCalled());
  });

  it("asks the server for any one dataset the caller may edit, not a page of recent ones", () => {
    state.granted = [Perm.datasetsView];
    render(<AddToDatasetButton messageId="m1" ratedDown />);
    expect(state.lastQuery).toEqual({ limit: 1, editable: true, enabled: true });
    expect(screen.getByRole("button", { name: "Add to dataset" })).toBeInTheDocument();
  });

  it("searches every dataset once the list stops short of them all", async () => {
    state.total = 250;
    render(<AddToDatasetButton messageId="m1" ratedDown />);
    await open();
    await userEvent.type(screen.getByPlaceholderText("Find a dataset"), "ret");
    await waitFor(() =>
      expect(state.lastQuery).toEqual(expect.objectContaining({ search: "ret" })),
    );
    state.datasets = [];
    await userEvent.type(screen.getByPlaceholderText("Find a dataset"), "x");
    expect(screen.getByPlaceholderText("Find a dataset")).toBeInTheDocument();
  });

  it("adds a rated-down answer as the counter-example to the first dataset it may edit", async () => {
    state.add.mockResolvedValue({});
    render(<AddToDatasetButton messageId="m1" ratedDown />);
    await open();
    await userEvent.click(screen.getByRole("combobox", { name: "Dataset" }));
    expect(screen.queryByRole("option", { name: "read only" })).toBeNull();
    await userEvent.keyboard("{Escape}");
    await userEvent.click(screen.getByRole("button", { name: "Add" }));

    await waitFor(() =>
      expect(state.add).toHaveBeenCalledWith({
        datasetId: "d1",
        messageId: "m1",
        answerAs: "counter_example",
        withHistory: false,
      }),
    );
    const [message, options] = vi.mocked(toast.success).mock.calls[0]! as unknown as [
      string,
      { action: { label: string; onClick: () => void } },
    ];
    expect([message, options.action.label]).toEqual(["Added to refunds", "Open dataset"]);
    options.action.onClick();
    expect(state.push).toHaveBeenCalledWith("/datasets/d1?tab=cases");
  });

  it("keeps an answer nobody rated down as the reference, into the dataset chosen", async () => {
    state.add.mockResolvedValue({});
    render(<AddToDatasetButton messageId="m2" ratedDown={false} />);
    await open();
    expect(screen.getByText("The question comes with the answer.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("combobox", { name: "Dataset" }));
    await userEvent.click(screen.getByRole("option", { name: "returns" }));
    await userEvent.click(screen.getByRole("combobox", { name: "Keep the answer as" }));
    await userEvent.click(screen.getByRole("option", { name: "Counter-example" }));
    await userEvent.click(screen.getByRole("combobox", { name: "Keep the answer as" }));
    await userEvent.click(screen.getByRole("option", { name: "Reference answer" }));
    await userEvent.click(screen.getByRole("button", { name: "Add" }));

    await waitFor(() =>
      expect(state.add).toHaveBeenCalledWith({
        datasetId: "d3",
        messageId: "m2",
        answerAs: "reference_answer",
        withHistory: false,
      }),
    );
  });

  it("says why an add was refused and stays open", async () => {
    state.add.mockRejectedValue(new Error("Conversation not found"));
    render(<AddToDatasetButton messageId="m1" ratedDown />);
    await open();
    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("starts a dataset for the answer when there is none to add to", async () => {
    state.datasets = [{ id: "d2", name: "read only", can_edit: false }];
    state.create.mockResolvedValue({ id: "d9", name: "Refund answers" });
    state.add.mockResolvedValue({});
    render(<AddToDatasetButton messageId="m1" ratedDown />);
    await open();

    const name = screen.getByRole("textbox", { name: "New dataset" });
    expect(name).toHaveValue("Answers from Activity");
    await userEvent.clear(name);
    expect(screen.getByRole("button", { name: "Add" })).toBeDisabled();
    await userEvent.type(name, "Refund answers");
    await userEvent.click(screen.getByRole("button", { name: "Add" }));

    await waitFor(() =>
      expect(state.add).toHaveBeenCalledWith({
        datasetId: "d9",
        messageId: "m1",
        answerAs: "counter_example",
        withHistory: false,
      }),
    );
    expect(state.create).toHaveBeenCalledWith({
      name: "Refund answers",
      description: null,
      visibility: "org",
    });
  });

  it("closes on Cancel without adding anything", async () => {
    render(<AddToDatasetButton messageId="m1" ratedDown />);
    await open();

    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(state.add).not.toHaveBeenCalled();
  });

  it("adds to the dataset the page was opened from, and offers the way back to it", async () => {
    state.asked = "d3";
    state.add.mockResolvedValue({});
    render(<AddToDatasetButton messageId="m1" ratedDown />);
    await open();

    expect(screen.getByRole("combobox", { name: "Dataset" })).toHaveTextContent("returns");
    await userEvent.click(screen.getByRole("button", { name: "Add" }));

    await waitFor(() => expect(toast.success).toHaveBeenCalled());
    const [, options] = vi.mocked(toast.success).mock.calls[0]! as unknown as [
      string,
      { action: { label: string; onClick: () => void } },
    ];
    expect(options.action.label).toBe("Back to returns");
    options.action.onClick();
    expect(state.push).toHaveBeenCalledWith("/datasets/d3?tab=cases");
  });

  it("keeps the conversation before the question only when asked to", async () => {
    state.add.mockResolvedValue({});
    render(<AddToDatasetButton messageId="m1" ratedDown />);
    await open();
    const history = screen.getByRole("combobox", { name: "The conversation before the question" });
    expect(history).toHaveTextContent("Only this question");
    await userEvent.click(history);
    await userEvent.click(screen.getByRole("option", { name: "With the conversation" }));
    await userEvent.click(screen.getByRole("button", { name: "Add" }));

    await waitFor(() =>
      expect(state.add).toHaveBeenCalledWith(expect.objectContaining({ withHistory: true })),
    );
  });

  it("offers the conversation first for a question that leans on it, and not at all for none", () => {
    const dialog = (question: string, earlier: boolean) => (
      <AddToDatasetDialog
        open
        onOpenChange={vi.fn()}
        messageId="m1"
        answerAs="reference_answer"
        askAnswerAs={false}
        asked={{ question, earlier }}
      />
    );
    const history = () =>
      screen.queryByRole("combobox", { name: "The conversation before the question" });
    const first = render(dialog("And how much to Toronto?", true));
    expect(history()).toHaveTextContent("With the conversation");
    first.unmount();

    const second = render(dialog("How long do refunds take for a card payment?", true));
    expect(history()).toHaveTextContent("Only this question");
    second.unmount();

    render(dialog("And how much to Toronto?", false));
    expect(history()).toBeNull();
  });
});
