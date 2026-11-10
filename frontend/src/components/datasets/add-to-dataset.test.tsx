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
  listingError: null as Error | null,
  refetch: vi.fn(),
  sourceLoading: false,
  sourceError: null as Error | null,
  add: vi.fn(),
  create: vi.fn(),
  asked: null as string | null,
  push: vi.fn(),
  source: { private_to_other: false, owner_name: null as string | null },
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
  useDatasets: (query: { editable?: boolean; search?: string }) => {
    state.lastQuery = query;
    const rows = query.editable
      ? state.datasets.filter((dataset) => dataset.can_edit)
      : state.datasets;
    return {
      datasets: query.search ? rows.filter((item) => item.name.includes(query.search ?? "")) : rows,
      total: state.total || rows.length,
      isLoading: state.isLoading,
      error: state.listingError,
      refetch: state.refetch,
      create: { mutateAsync: state.create, isPending: false },
    };
  },
  useAddToDataset: () => ({ mutateAsync: state.add, isPending: false }),
  useDatasetSource: () => ({
    data: state.sourceLoading ? undefined : state.source,
    error: state.sourceError,
    isLoading: state.sourceLoading,
  }),
}));
vi.mock("@/components/chat/markdown-content", () => ({
  MarkdownContent: ({ content }: { content: string }) => <div>{content}</div>,
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
    state.listingError = null;
    state.sourceLoading = false;
    state.sourceError = null;
    localStorage.clear();
    state.source = { private_to_other: false, owner_name: null };
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
    await userEvent.click(screen.getByRole("radio", { name: /Counter-example/ }));
    expect(screen.getByRole("radio", { name: /Counter-example/ })).toBeChecked();
    await userEvent.click(screen.getByRole("radio", { name: /Reference answer/ }));
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
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Conversation not found"),
    );
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

  it("keeps the newly created dataset when adding fails, and reuses it on retry", async () => {
    state.datasets = [];
    state.create.mockResolvedValue({ id: "new", name: "Answers from Activity" });
    state.add.mockRejectedValueOnce(new Error("Add refused")).mockResolvedValueOnce({});
    render(<AddToDatasetButton messageId="m1" ratedDown={false} />);
    await open();
    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    await screen.findByRole("alert");
    expect(screen.getByRole("combobox", { name: "Dataset" })).toHaveTextContent(
      "Answers from Activity",
    );
    state.datasets = [
      { id: "other", name: "Other", can_edit: true },
      { id: "new", name: "Answers from Activity", can_edit: true },
    ];
    await userEvent.click(screen.getByRole("radio", { name: /Counter-example/ }));
    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(state.add).toHaveBeenCalledTimes(2));
    expect(state.create).toHaveBeenCalledTimes(1);
    expect(state.add.mock.calls[1]?.[0]).toEqual(expect.objectContaining({ datasetId: "new" }));
  });

  it("never creates a dataset or silently changes destination for an unmatched search", async () => {
    state.total = 250;
    render(<AddToDatasetButton messageId="m1" ratedDown={false} />);
    await open();
    await userEvent.type(screen.getByPlaceholderText("Find a dataset"), "unknown");
    await screen.findByText("No datasets match your search.");
    expect(screen.queryByRole("textbox", { name: "New dataset" })).toBeNull();
    expect(screen.getByRole("button", { name: "Add" })).toBeDisabled();
    expect(state.create).not.toHaveBeenCalled();
    await userEvent.clear(screen.getByPlaceholderText("Find a dataset"));
    await waitFor(() => expect(screen.getByRole("button", { name: "Add" })).toBeEnabled());
  });

  it("requires an explicit destination when searching instead of picking the first match", async () => {
    state.total = 250;
    render(<AddToDatasetButton messageId="m1" ratedDown={false} />);
    await open();
    await userEvent.type(screen.getByPlaceholderText("Find a dataset"), "ret");
    await waitFor(() =>
      expect(state.lastQuery).toEqual(expect.objectContaining({ search: "ret" })),
    );
    expect(screen.getByRole("button", { name: "Add" })).toBeDisabled();
    await userEvent.click(screen.getByRole("combobox", { name: "Dataset" }));
    await userEvent.click(screen.getByRole("option", { name: "returns" }));
    expect(screen.getByRole("button", { name: "Add" })).toBeEnabled();
  });

  it("shows a listing failure, blocks creation and lets the reader retry", async () => {
    state.datasets = [];
    state.listingError = new Error("Listing failed");
    render(<AddToDatasetButton messageId="m1" ratedDown={false} />);
    await open();
    expect(screen.getByRole("alert")).toHaveTextContent("Listing failed");
    expect(screen.getByRole("button", { name: "Add" })).toBeDisabled();
    expect(screen.queryByRole("textbox", { name: "New dataset" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(state.refetch).toHaveBeenCalled();
  });

  it("previews the selected source and omits history when the question starts the conversation", async () => {
    render(
      <AddToDatasetButton
        messageId="m1"
        ratedDown={false}
        asked={{ question: "Refund?", earlier: false }}
        answer="Five days."
      />,
    );
    await open();
    expect(
      screen.queryByRole("combobox", { name: "The conversation before the question" }),
    ).toBeNull();
    await userEvent.click(screen.getByText("View source messages"));
    expect(screen.getByText("Refund?")).toBeVisible();
    expect(screen.getByText("Five days.")).toBeVisible();
  });

  it("does not submit while datasets are loading", async () => {
    state.datasets = [];
    state.isLoading = true;
    render(<AddToDatasetButton messageId="m1" ratedDown />);
    await open();
    expect(screen.getByRole("combobox", { name: "Dataset" })).toBeDisabled();
    expect(screen.getByText("Loading datasets…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add" })).toBeDisabled();
  });

  it("waits for the source privacy check before allowing an add", async () => {
    state.sourceLoading = true;
    render(<AddToDatasetButton messageId="m1" ratedDown />);
    await open();
    expect(screen.getByText("Checking source privacy…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add" })).toBeDisabled();
  });

  it("shows the source refusal without allowing an add", async () => {
    state.sourceError = new Error("Source unavailable");
    render(<AddToDatasetButton messageId="m1" ratedDown />);
    await open();
    expect(screen.getByRole("alert")).toHaveTextContent("Source unavailable");
    expect(screen.getByRole("button", { name: "Add" })).toBeDisabled();
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

  it.each(["I need an invoice for order 12", "Do you ship?", "Refund policy?"])(
    "copies no conversation for %o unless asked to",
    async (question) => {
      state.add.mockResolvedValue({});
      render(
        <AddToDatasetDialog
          open
          onOpenChange={vi.fn()}
          messageId="m1"
          answerAs="reference_answer"
          askAnswerAs={false}
          asked={{ question, earlier: true }}
        />,
      );
      expect(
        screen.getByRole("combobox", { name: "The conversation before the question" }),
      ).toHaveTextContent("Only this question");
      expect(screen.queryByText(/looks like a follow-up/)).toBeNull();
      await userEvent.click(screen.getByRole("button", { name: "Add" }));
      await waitFor(() =>
        expect(state.add).toHaveBeenCalledWith(expect.objectContaining({ withHistory: false })),
      );
    },
  );

  it("points out a follow-up without choosing it, and asks nothing with no conversation", () => {
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
    expect(history()).toHaveTextContent("Only this question");
    expect(
      screen.getByText("This looks like a follow-up to the conversation before it."),
    ).toBeInTheDocument();
    first.unmount();

    render(dialog("And how much to Toronto?", false));
    expect(history()).toBeNull();
  });
});

it.each([true, false])(
  "warns before copying somebody else's private conversation (%s)",
  async (privateToOther) => {
    state.granted = [Perm.datasetsEdit];
    state.datasets = [{ id: "d1", name: "refunds", can_edit: true }];
    state.isLoading = false;
    state.source = { private_to_other: privateToOther, owner_name: privateToOther ? "Pat" : null };
    render(
      <AddToDatasetDialog
        open
        onOpenChange={vi.fn()}
        messageId="m-private"
        answerAs="counter_example"
        askAnswerAs
      />,
    );
    if (privateToOther)
      expect(screen.getByRole("note")).toHaveTextContent("This conversation is private to Pat.");
    else expect(screen.queryByRole("note")).toBeNull();
  },
);
