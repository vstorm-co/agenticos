import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-error";
import { CaseEditorDialog } from "./case-editor-dialog";
import { draftOf, EMPTY_DRAFT } from "./case-form";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
import { toast } from "sonner";
vi.mock("@/hooks/use-agents", () => ({
  useCapabilityCatalog: () => ({
    capabilities: [
      { id: "kb", tools: [{ id: "search_kb" }, { id: "fetch_page" }] },
      { id: "web", tools: [{ id: "fetch_page" }] },
    ],
  }),
}));

const STORED = {
  input: "How long is the return window?",
  history: [
    { role: "user" as const, content: "I bought a kettle" },
    { role: "assistant" as const, content: "How can I help?" },
  ],
  reference_answer: "30 days",
  counter_example: "90 days",
  expected_tool_calls: [{ tool: "search_kb", args: { q: "refund" } }],
  order_mode: "in_order" as const,
  checks: [{ type: "contains", value: "30 days" }],
  tags: ["returns"],
  note: "Asked weekly",
};

const input = () => screen.getByLabelText(/^Input/);
const save = () => screen.getByRole("button", { name: "Save case" });
const answer = () => screen.getByLabelText("Reference answer");

function mount(onSave?: (content: unknown) => Promise<unknown>, onOpenChange = vi.fn()) {
  render(
    <CaseEditorDialog
      open
      onOpenChange={onOpenChange}
      initial={EMPTY_DRAFT}
      onSave={onSave}
      title="Add case"
    />,
  );
  return onOpenChange;
}

describe("CaseEditorDialog", () => {
  beforeEach(() => vi.clearAllMocks());

  it("saves what was written and closes", async () => {
    const onSave = vi.fn().mockResolvedValue({});
    const onOpenChange = mount(onSave);
    expect(save()).toBeDisabled();

    expect(screen.getByRole("status")).toHaveTextContent("Write the input the agent answers.");
    await userEvent.type(input(), "How long?");
    expect(screen.getByRole("status")).toHaveTextContent(/a case needs something to test/);
    expect(save()).toBeDisabled();
    await userEvent.type(answer(), "30 days");
    expect(screen.queryByRole("status")).toBeNull();
    await userEvent.type(screen.getByLabelText("Tags"), "returns");
    expect(screen.getByText(/order and other calls do not matter/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("combobox", { name: "How expected calls are matched" }));
    await userEvent.click(screen.getByRole("option", { name: "In this order" }));
    expect(screen.getByText(/other calls may come between them/)).toBeInTheDocument();
    await userEvent.click(save());

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        input: "How long?",
        reference_answer: "30 days",
        tags: ["returns"],
        order_mode: "in_order",
      }),
    );
  });

  it("builds the conversation, the tool calls and the checks row by row", async () => {
    const onSave = vi.fn().mockResolvedValue({});
    mount(onSave);
    await userEvent.type(input(), "And for a kettle?");

    await userEvent.click(screen.getByRole("button", { name: "Add a turn" }));
    await userEvent.type(screen.getByLabelText("Turn 1: what was said"), "I bought a kettle");
    await userEvent.click(screen.getByRole("button", { name: "Add a turn" }));
    await userEvent.type(screen.getByLabelText("Turn 2: what was said"), "Happy to help");
    await userEvent.click(screen.getByRole("combobox", { name: "Turn 2: who speaks" }));
    await userEvent.click(screen.getByRole("option", { name: "Person" }));
    await userEvent.click(screen.getByRole("button", { name: "Add a turn" }));
    await userEvent.click(screen.getByRole("button", { name: "Remove turn 3" }));

    await userEvent.click(screen.getByRole("button", { name: "Add a tool call" }));
    const tool = screen.getByLabelText("Call 1: tool");
    expect(document.getElementById(tool.getAttribute("list")!)?.children).toHaveLength(2);
    await userEvent.type(tool, "search_kb");
    await userEvent.type(screen.getByLabelText("Call 1: arguments"), '{{"q": "kettle"}');
    await userEvent.click(screen.getByRole("button", { name: "Add a tool call" }));
    await userEvent.click(screen.getByRole("button", { name: "Remove call 2" }));

    await userEvent.click(screen.getByRole("button", { name: "Add a check" }));
    await userEvent.type(screen.getByLabelText("Check 1: what it checks"), "30 days");
    await userEvent.click(screen.getByRole("button", { name: "Add a check" }));
    await userEvent.click(screen.getByRole("combobox", { name: "Check 2: type" }));
    await userEvent.click(screen.getByRole("option", { name: "Costs at most (USD)" }));
    await userEvent.type(screen.getByLabelText("Check 2: what it checks"), "0.05");
    await userEvent.click(screen.getByRole("button", { name: "Add a check" }));
    await userEvent.click(screen.getByRole("combobox", { name: "Check 3: type" }));
    await userEvent.click(screen.getByRole("option", { name: "Judge criterion" }));
    await userEvent.type(screen.getByLabelText("Check 3: what it checks"), "Polite");
    await userEvent.click(screen.getByRole("button", { name: "Add a check" }));
    await userEvent.click(screen.getByRole("combobox", { name: "Check 4: type" }));
    await userEvent.click(screen.getByRole("option", { name: "Matches a JSON schema" }));
    await userEvent.type(screen.getByLabelText("Check 4: what it checks"), '{{"type": "object"}');
    await userEvent.click(screen.getByRole("button", { name: "Remove check 4" }));
    await userEvent.click(save());

    await waitFor(() => expect(onSave).toHaveBeenCalled());
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        history: [
          { role: "user", content: "I bought a kettle" },
          { role: "user", content: "Happy to help" },
        ],
        expected_tool_calls: [{ tool: "search_kb", args: { q: "kettle" } }],
        checks: [
          { type: "contains", value: "30 days" },
          { type: "max_cost_usd", value: 0.05 },
          { type: "judge", criterion: "Polite" },
        ],
      }),
    );
  });

  it("marks a check it cannot read without sending anything", async () => {
    const onSave = vi.fn();
    mount(onSave);
    await userEvent.type(input(), "q");
    await userEvent.click(screen.getByRole("button", { name: "Add a check" }));
    await userEvent.click(save());

    expect(
      await screen.findByText("Say what each check checks, or remove it."),
    ).toBeInTheDocument();
    expect(onSave).not.toHaveBeenCalled();
    await userEvent.type(screen.getByLabelText("Check 1: what it checks"), "x");
    expect(screen.queryByText("Say what each check checks, or remove it.")).toBeNull();
  });

  it("opens a stored case as it reads, and edits it only on Edit", async () => {
    const onSave = vi.fn().mockResolvedValue({});
    render(
      <CaseEditorDialog
        open
        onOpenChange={vi.fn()}
        initial={draftOf({ ...STORED, checks: [...STORED.checks, { type: "from_the_future" }] })}
        viewing={STORED}
        onSave={onSave}
        title="Case"
      />,
    );

    expect(screen.getByText("I bought a kettle")).toBeInTheDocument();
    expect(screen.getByText("How can I help?")).toBeInTheDocument();
    expect(screen.getByText('search_kb {"q":"refund"}')).toBeInTheDocument();
    expect(screen.getByText("contains 30 days")).toBeInTheDocument();
    expect(screen.getByText("returns")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save case" })).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Edit" }));
    expect(screen.getByLabelText("Call 1: arguments")).toHaveValue('{"q":"refund"}');
    expect(screen.getAllByText("from_the_future").length).toBeGreaterThan(0);
    expect(screen.getByRole("combobox", { name: "Check 2: type" })).toBeDisabled();
    await userEvent.click(save());

    await waitFor(() => expect(onSave).toHaveBeenCalled());
    expect(onSave.mock.calls[0]![0].checks).toEqual([
      { type: "contains", value: "30 days" },
      { type: "from_the_future" },
    ]);
  });

  it("reads a case it may not change without offering an edit", () => {
    render(
      <CaseEditorDialog
        open
        onOpenChange={vi.fn()}
        initial={draftOf({
          ...STORED,
          history: [],
          tags: [],
          note: null,
          checks: [],
          expected_tool_calls: [],
        })}
        viewing={{
          ...STORED,
          history: [],
          tags: [],
          note: null,
          checks: [],
          expected_tool_calls: [],
          reference_answer: null,
          counter_example: null,
        }}
        title="Case"
      />,
    );

    expect(screen.getByText("How long is the return window?")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
    expect(screen.getByText(/Read-only/)).toBeInTheDocument();
  });

  it("puts the server's refusal under the field it names, and the rest in a toast", async () => {
    const refusal = new ApiError(400, "invalid", {
      error: {
        code: "BAD_REQUEST",
        message: "invalid",
        details: {
          fields: [
            { field: "input", message: "Too long" },
            { field: "elsewhere", message: "Unrelated" },
          ],
        },
      },
    });
    const onOpenChange = mount(vi.fn().mockRejectedValue(refusal));
    await userEvent.type(input(), "q");
    await userEvent.type(answer(), "a");
    await userEvent.click(save());

    expect(await screen.findByText("Too long")).toBeInTheDocument();
    expect(toast.error).toHaveBeenCalledWith("elsewhere: Unrelated");
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });

  it("needs no toast when every refusal has a field to stand under", async () => {
    const refusal = new ApiError(400, "invalid", {
      error: {
        code: "BAD_REQUEST",
        message: "invalid",
        details: { fields: [{ field: "note", message: "Too short" }] },
      },
    });
    mount(vi.fn().mockRejectedValue(refusal));
    await userEvent.type(input(), "q");
    await userEvent.type(answer(), "a");
    await userEvent.click(save());
    expect(await screen.findByText("Too short")).toBeInTheDocument();
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("only reads a case it may not change", async () => {
    const onOpenChange = mount(undefined);
    expect(screen.queryByRole("button", { name: "Save case" })).toBeNull();
    expect(screen.getByText(/Read-only/)).toBeInTheDocument();
    const [footerClose] = screen
      .getAllByRole("button", { name: "Close" })
      .filter((button) => button.textContent === "Close");
    await userEvent.click(footerClose!);
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
