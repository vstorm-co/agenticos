import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";

import { ViewSelect } from "./view-select";
import { ApiError } from "@/lib/api-client";
import type { TableViewRead } from "@/types/tables";

const config = {
  filters: [],
  sort: { by: "c1", direction: "asc" as const },
  visible_columns: null,
  group_by: null,
};

function view(overrides: Partial<TableViewRead> = {}): TableViewRead {
  return {
    id: "v1",
    table_id: "t1",
    owner_user_id: "u1",
    name: "Mine",
    kind: "table",
    visibility: "private",
    config,
    can_manage: true,
    can_delete: true,
    created_at: "2026-09-23T00:00:00Z",
    updated_at: null,
    ...overrides,
  };
}

const taken = () =>
  new ApiError(409, "A view named 'Mine' already exists.", {
    error: {
      code: "ALREADY_EXISTS",
      message: "A view named 'Mine' already exists.",
      details: { name: "Mine" },
    },
  });

function deferred() {
  let resolve!: () => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<void>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

type Props = ComponentProps<typeof ViewSelect>;

function renderSelect(overrides: Partial<Props> = {}) {
  const props: Props = {
    kind: "table",
    views: [view()],
    activeViewId: null,
    onSelect: vi.fn(),
    onCreate: vi.fn().mockResolvedValue(undefined),
    onRename: vi.fn().mockResolvedValue(undefined),
    onDelete: vi.fn(),
    canCreate: true,
    ...overrides,
  };
  render(<ViewSelect {...props} />);
  return props;
}

async function openCreate(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: /new view/i }));
  return screen.getByRole("dialog");
}

describe("ViewSelect", () => {
  it("shows the unsaved-view placeholder when no view is active", () => {
    renderSelect({ views: [] });
    expect(screen.getByRole("combobox", { name: /select a table view/i })).toHaveTextContent(
      "Unsaved view",
    );
  });

  it("selecting a saved view calls onSelect with its id", async () => {
    const user = userEvent.setup();
    const { onSelect } = renderSelect();

    await user.click(screen.getByRole("combobox", { name: /select a table view/i }));
    await user.click(screen.getByRole("option", { name: "Mine" }));

    expect(onSelect).toHaveBeenCalledWith("v1");
  });

  it("selecting the unsaved-view option calls onSelect with null", async () => {
    const user = userEvent.setup();
    const { onSelect } = renderSelect({ activeViewId: "v1" });

    await user.click(screen.getByRole("combobox", { name: /select a table view/i }));
    await user.click(screen.getByRole("option", { name: "Unsaved view" }));

    expect(onSelect).toHaveBeenCalledWith(null);
  });

  it("hides the new-view control when the caller may not create one", () => {
    renderSelect({ canCreate: false });
    expect(screen.queryByRole("button", { name: /new view/i })).not.toBeInTheDocument();
  });

  describe("creating a view", () => {
    it("creates it with the typed name and chosen visibility, holding the dialog open until it lands", async () => {
      const write = deferred();
      const onCreate = vi.fn().mockReturnValue(write.promise);
      const user = userEvent.setup();
      renderSelect({ onCreate });

      const dialog = await openCreate(user);
      fireEvent.change(within(dialog).getByLabelText("View name"), {
        target: { value: "  My list " },
      });
      await user.click(within(dialog).getByRole("combobox", { name: /visibility/i }));
      await user.click(screen.getByRole("option", { name: "Shared" }));
      await user.click(within(dialog).getByRole("button", { name: /^save$/i }));

      expect(onCreate).toHaveBeenCalledWith("My list", "shared");
      expect(screen.getByRole("dialog")).toBeInTheDocument();
      expect(within(dialog).getByRole("button", { name: /^save$/i })).toBeDisabled();

      write.resolve();
      await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    });

    it("keeps the dialog open and shows a taken name beside the input", async () => {
      const user = userEvent.setup();
      renderSelect({ onCreate: vi.fn().mockRejectedValue(taken()) });

      const dialog = await openCreate(user);
      fireEvent.change(within(dialog).getByLabelText("View name"), { target: { value: "Mine" } });
      await user.click(within(dialog).getByRole("button", { name: /^save$/i }));

      expect(await within(dialog).findByText(/already exists/i)).toBeInTheDocument();
      expect(within(dialog).getByLabelText("View name")).toHaveAttribute("aria-invalid", "true");
      expect(within(dialog).getByLabelText("View name")).toHaveValue("Mine");
    });

    it("shows a failure that is not about the name, rather than stopping silently", async () => {
      // Only the name problem used to render; a 404 (edit access lost) or a
      // 500 left the dialog open with no message at all.
      const user = userEvent.setup();
      renderSelect({ onCreate: vi.fn().mockRejectedValue(new ApiError(404, "Table not found")) });

      const dialog = await openCreate(user);
      fireEvent.change(within(dialog).getByLabelText("View name"), { target: { value: "Board" } });
      await user.click(within(dialog).getByRole("button", { name: /^save$/i }));

      expect(await within(dialog).findByText("Table not found")).toBeInTheDocument();
      expect(within(dialog).getByLabelText("View name")).not.toHaveAttribute("aria-invalid");
    });

    it("reopens with no error left over from the last attempt", async () => {
      const user = userEvent.setup();
      renderSelect({ onCreate: vi.fn().mockRejectedValue(taken()) });

      let dialog = await openCreate(user);
      fireEvent.change(within(dialog).getByLabelText("View name"), { target: { value: "Mine" } });
      await user.click(within(dialog).getByRole("button", { name: /^save$/i }));
      await within(dialog).findByText(/already exists/i);
      await user.click(within(dialog).getByRole("button", { name: /^cancel$/i }));

      dialog = await openCreate(user);

      expect(within(dialog).queryByText(/already exists/i)).not.toBeInTheDocument();
      expect(within(dialog).getByLabelText("View name")).toHaveValue("");
      expect(within(dialog).getByLabelText("View name")).not.toHaveAttribute("aria-invalid");
    });

    it("leaves a reopened dialog alone when a save from before it closed settles", async () => {
      // Cancelled mid-save and opened again, the dialog used to close itself
      // - or show the old save's error - when that earlier write answered.
      const write = deferred();
      const user = userEvent.setup();
      renderSelect({ onCreate: vi.fn().mockReturnValueOnce(write.promise) });

      let dialog = await openCreate(user);
      fireEvent.change(within(dialog).getByLabelText("View name"), { target: { value: "Old" } });
      await user.click(within(dialog).getByRole("button", { name: /^save$/i }));
      await user.click(within(dialog).getByRole("button", { name: /^cancel$/i }));
      dialog = await openCreate(user);
      fireEvent.change(within(dialog).getByLabelText("View name"), { target: { value: "New" } });

      write.reject(taken());
      await new Promise((resolve) => setTimeout(resolve, 0));

      expect(screen.getByRole("dialog")).toBeInTheDocument();
      expect(within(dialog).queryByText(/already exists/i)).not.toBeInTheDocument();
      expect(within(dialog).getByRole("button", { name: /^save$/i })).toBeEnabled();
    });

    it("disables save while the name is blank", async () => {
      const user = userEvent.setup();
      renderSelect();

      const dialog = await openCreate(user);

      expect(within(dialog).getByRole("button", { name: /^save$/i })).toBeDisabled();
    });

    it("cancelling does not call onCreate", async () => {
      const user = userEvent.setup();
      const { onCreate } = renderSelect();

      const dialog = await openCreate(user);
      await user.click(within(dialog).getByRole("button", { name: /^cancel$/i }));

      expect(onCreate).not.toHaveBeenCalled();
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  it("shows no manage controls for a view the caller cannot manage", () => {
    renderSelect({ views: [view({ can_manage: false, can_delete: false })], activeViewId: "v1" });
    expect(screen.queryByRole("button", { name: /^rename$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^delete$/i })).not.toBeInTheDocument();
  });

  it("offers an owner who lost edit access a delete but no rename", () => {
    // Renaming needs edit access to the table and deleting does not; the one
    // flag both used to read said yes to a rename the server then refused.
    renderSelect({ views: [view({ can_manage: false, can_delete: true })], activeViewId: "v1" });
    expect(screen.queryByRole("button", { name: /^rename$/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^delete$/i })).toBeInTheDocument();
  });

  it("shows no manage controls when no view is active", () => {
    renderSelect();
    expect(screen.queryByRole("button", { name: /^rename$/i })).not.toBeInTheDocument();
  });

  describe("renaming the active view", () => {
    it("renames it with the edited, trimmed name and closes once the rename lands", async () => {
      const user = userEvent.setup();
      const { onRename } = renderSelect({ activeViewId: "v1" });

      await user.click(screen.getByRole("button", { name: /^rename$/i }));
      const input = screen.getByLabelText("View name");
      expect(input).toHaveValue("Mine");
      fireEvent.change(input, { target: { value: "  Renamed  " } });
      await user.click(screen.getByRole("button", { name: /^save$/i }));

      expect(onRename).toHaveBeenCalledWith("v1", "Renamed");
      await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    });

    it("stays open with the typed name and the conflict when the rename is refused", async () => {
      // The dialog used to close before the write answered, taking the typed
      // name with it; only a toast said the name was taken.
      const user = userEvent.setup();
      renderSelect({ activeViewId: "v1", onRename: vi.fn().mockRejectedValue(taken()) });

      await user.click(screen.getByRole("button", { name: /^rename$/i }));
      fireEvent.change(screen.getByLabelText("View name"), { target: { value: "Taken" } });
      await user.click(screen.getByRole("button", { name: /^save$/i }));

      const dialog = screen.getByRole("dialog");
      expect(await within(dialog).findByText(/already exists/i)).toBeInTheDocument();
      expect(within(dialog).getByLabelText("View name")).toHaveValue("Taken");
    });

    it("cancelling does not call onRename", async () => {
      const user = userEvent.setup();
      const { onRename } = renderSelect({ activeViewId: "v1" });

      await user.click(screen.getByRole("button", { name: /^rename$/i }));
      await user.click(screen.getByRole("button", { name: /^cancel$/i }));

      expect(onRename).not.toHaveBeenCalled();
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });

    it("closing via the dialog's own close control does not rename", async () => {
      const user = userEvent.setup();
      const { onRename } = renderSelect({ activeViewId: "v1" });

      await user.click(screen.getByRole("button", { name: /^rename$/i }));
      await user.click(screen.getByRole("button", { name: /^close$/i }));

      expect(onRename).not.toHaveBeenCalled();
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  it("deletes the active view after confirming, naming it in the confirmation", async () => {
    const user = userEvent.setup();
    const { onDelete } = renderSelect({ activeViewId: "v1" });

    await user.click(screen.getByRole("button", { name: /^delete$/i }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText(/Delete “Mine”\?/)).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: /^delete$/i }));

    expect(onDelete).toHaveBeenCalledWith("v1");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("cancelling the delete confirmation does not call onDelete", async () => {
    const user = userEvent.setup();
    const { onDelete } = renderSelect({ activeViewId: "v1" });

    await user.click(screen.getByRole("button", { name: /^delete$/i }));
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /^cancel$/i }));

    expect(onDelete).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
