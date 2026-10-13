import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-error";
import { CaseEditorDialog } from "./case-editor-dialog";
import { EMPTY_DRAFT } from "./case-form";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
import { toast } from "sonner";

const input = () => screen.getByLabelText(/^Input/);
const save = () => screen.getByRole("button", { name: "Save case" });

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

    await userEvent.type(input(), "How long?");
    await userEvent.type(screen.getByLabelText("Tags"), "returns");
    expect(screen.getByText(/order and other calls do not matter/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("combobox", { name: "How expected calls are matched" }));
    await userEvent.click(screen.getByRole("option", { name: "In this order" }));
    expect(screen.getByText(/other calls may come between them/)).toBeInTheDocument();
    await userEvent.click(save());

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ input: "How long?", tags: ["returns"], order_mode: "in_order" }),
    );
  });

  it("marks a structured field that is not JSON without sending anything", async () => {
    const onSave = vi.fn();
    mount(onSave);
    await userEvent.type(input(), "q");
    await userEvent.type(screen.getByLabelText("Checks"), "not json");
    await userEvent.click(save());

    expect(await screen.findByText("This is not valid JSON.")).toBeInTheDocument();
    expect(onSave).not.toHaveBeenCalled();
    await userEvent.type(screen.getByLabelText("Checks"), "!");
    expect(screen.queryByText("This is not valid JSON.")).toBeNull();
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
