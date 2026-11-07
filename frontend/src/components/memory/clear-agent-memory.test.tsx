import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ClearAgentMemory } from "./clear-agent-memory";

vi.mock("next-intl", async () => ({
  useTranslations: (await import("@/test-utils/intl")).keyTranslations(),
}));

const mutateAsync = vi.fn<() => Promise<unknown>>();
let pending = false;
vi.mock("@/hooks/use-memory", () => ({
  useClearAgentMemory: () => ({ mutateAsync, isPending: pending }),
}));

beforeEach(() => {
  vi.clearAllMocks();
  pending = false;
  mutateAsync.mockResolvedValue({ notes_deleted: 3 });
});

function mount(props: Partial<Parameters<typeof ClearAgentMemory>[0]> = {}) {
  return render(<ClearAgentMemory agentId="a-1" {...props} />);
}

async function openDialog() {
  await userEvent.click(screen.getByRole("button", { name: "clearAction" }));
  return screen.findByRole("dialog");
}

describe("ClearAgentMemory", () => {
  it("does not clear anything until the phrase is typed", async () => {
    // Every person's and every room's notes go at once and nothing brings them
    // back, so a single click must not be enough.
    mount();

    const dialog = await openDialog();

    expect(within(dialog).getByRole("button", { name: "clearAction" })).toBeDisabled();
    expect(mutateAsync).not.toHaveBeenCalled();
  });

  it("clears once the phrase is typed", async () => {
    mount();
    const dialog = await openDialog();

    await userEvent.type(within(dialog).getByRole("textbox"), "CLEAR");
    await userEvent.click(within(dialog).getByRole("button", { name: "clearAction" }));

    await waitFor(() => expect(mutateAsync).toHaveBeenCalled());
  });

  it("describes what is deleted", () => {
    mount();

    expect(screen.getByText("clearBody")).toBeInTheDocument();
  });

  it("is inert for a caller who may not edit the agent", () => {
    mount({ disabled: true });

    expect(screen.getByRole("button", { name: "clearAction" })).toBeDisabled();
  });

  it("is inert while a clear is running", () => {
    pending = true;
    mount();

    expect(screen.getByRole("button", { name: "clearAction" })).toBeDisabled();
  });
});
