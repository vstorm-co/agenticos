import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-error";
import { useSavedVisualsStore } from "@/stores/visual-stream-store";
import { VisualSaveDialog } from "./visual-save-dialog";

const { mutateAsync, push, toast } = vi.hoisted(() => ({
  mutateAsync: vi.fn(),
  push: vi.fn(),
  toast: { success: vi.fn(), error: vi.fn() },
}));
vi.mock("@/hooks/use-publish-visual", () => ({
  usePublishVisual: () => ({ mutateAsync, isPending: false }),
}));
vi.mock("@/lib/locale-navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("sonner", () => ({ toast }));

function open(updates: string | null = null) {
  const onOpenChange = vi.fn();
  render(
    <VisualSaveDialog
      open
      onOpenChange={onOpenChange}
      conversationId="c1"
      visualId="v1"
      title="Plakat A3 — Łódź"
      updates={updates}
    />,
  );
  return onOpenChange;
}

const APP = {
  artifact_id: "a1",
  version: 1,
  name: "plakat-a3-lodz",
  title: "Plakat A3 — Łódź",
  created: true,
  unchanged: false,
  url: "/apps/a1",
};

describe("VisualSaveDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useSavedVisualsStore.setState({ saved: {} });
  });

  it("fills in the title and a name made from it, and saves on Enter", async () => {
    mutateAsync.mockResolvedValue(APP);
    const onOpenChange = open();

    expect(screen.getByLabelText("Name")).toHaveValue("plakat-a3-lodz");
    fireEvent.submit(screen.getByLabelText("Name").closest("form")!);

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(mutateAsync).toHaveBeenCalledWith({
      conversationId: "c1",
      visualId: "v1",
      data: { name: "plakat-a3-lodz", title: "Plakat A3 — Łódź" },
    });
    expect(useSavedVisualsStore.getState().saved.v1).toEqual({
      artifactId: "a1",
      name: "plakat-a3-lodz",
      version: 1,
      url: "/apps/a1",
    });
    const [said, options] = toast.success.mock.calls[0]!;
    expect(said).toBe("Saved as an app, version 1");
    options.action.onClick();
    expect(push).toHaveBeenCalledWith("/apps/a1");
  });

  it("updates the app an earlier version was saved as", async () => {
    mutateAsync.mockResolvedValue({ ...APP, version: 2, unchanged: true });
    open("flow");
    expect(screen.getByText("Update the app")).toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toHaveValue("flow");
    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "  " } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith(
        "The app already has exactly this version",
        expect.anything(),
      ),
    );
    expect(mutateAsync.mock.calls[0]![0].data).toEqual({ name: "flow", title: undefined });
  });

  it("marks the name the server refused, and clears it as it is edited", async () => {
    mutateAsync.mockRejectedValue(
      new ApiError(400, "bad", {
        error: {
          code: "BAD_REQUEST",
          message: "bad",
          details: { fields: [{ field: "name", message: "Not a valid app name" }] },
        },
      }),
    );
    open();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Not a valid app name")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "ok" } });
    expect(screen.queryByText("Not a valid app name")).toBeNull();
    expect(screen.getByText(/Lower-case letters/)).toBeInTheDocument();
  });

  it("says what went wrong when it is not about a field", async () => {
    mutateAsync.mockRejectedValue(new ApiError(500, "Server fell over"));
    open();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Server fell over"));
  });

  it("marks a refused title", async () => {
    mutateAsync.mockRejectedValue(
      new ApiError(422, "bad", {
        error: {
          code: "VALIDATION_ERROR",
          message: "bad",
          details: { fields: [{ field: "title", message: "Too long" }] },
        },
      }),
    );
    open();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Too long")).toBeInTheDocument();
  });

  it("cancels, and will not save without a name", () => {
    const onOpenChange = open();
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: " " } });
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
