import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ForgetMe } from "./forget-me";

vi.mock("next-intl", async () => ({
  useTranslations: (await import("@/test-utils/intl")).keyTranslations(),
}));

const mutateAsync = vi.fn<(userId: string) => Promise<unknown>>();
let pending = false;
vi.mock("@/hooks/use-memory", () => ({
  useForgetPersonMemory: () => ({ mutateAsync, isPending: pending }),
}));

beforeEach(() => {
  vi.clearAllMocks();
  pending = false;
  mutateAsync.mockResolvedValue({ notes_deleted: 2, mem0_agents_cleared: 1 });
});

describe("ForgetMe", () => {
  it("erases the person looking at it and nobody else", async () => {
    render(<ForgetMe userId="u-1" />);

    await userEvent.click(screen.getByRole("button", { name: "forgetAction" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByRole("textbox"), "FORGET");
    await userEvent.click(within(dialog).getByRole("button", { name: "forgetAction" }));

    await waitFor(() => expect(mutateAsync).toHaveBeenCalledWith("u-1"));
  });

  it("asks for the phrase first", async () => {
    // It spans every agent in the organization and nothing brings it back.
    render(<ForgetMe userId="u-1" />);

    await userEvent.click(screen.getByRole("button", { name: "forgetAction" }));
    const dialog = await screen.findByRole("dialog");

    expect(within(dialog).getByRole("button", { name: "forgetAction" })).toBeDisabled();
    expect(mutateAsync).not.toHaveBeenCalled();
  });

  it("is inert while the erasure runs", () => {
    pending = true;
    render(<ForgetMe userId="u-1" />);

    expect(screen.getByRole("button", { name: "forgetAction" })).toBeDisabled();
  });
});
