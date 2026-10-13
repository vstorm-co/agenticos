import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ForgetMemberMemory } from "./forget-member-memory";

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
  mutateAsync.mockResolvedValue({ notes_deleted: 0, mem0_agents_cleared: 0 });
});

describe("ForgetMemberMemory", () => {
  it("names who is being forgotten, because the row is one of many", async () => {
    render(<ForgetMemberMemory userId="u-2" name="Anna Kowalska" />);

    expect(screen.getByRole("button", { name: "forgetNamed" })).toBeInTheDocument();
  });

  it("erases the member the row names", async () => {
    render(<ForgetMemberMemory userId="u-2" name="Anna Kowalska" />);

    await userEvent.click(screen.getByRole("button", { name: "forgetNamed" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByRole("textbox"), "FORGET");
    await userEvent.click(within(dialog).getByRole("button", { name: "forgetAction" }));

    await waitFor(() => expect(mutateAsync).toHaveBeenCalledWith("u-2"));
  });

  it("asks for the phrase before erasing somebody else's memory", async () => {
    render(<ForgetMemberMemory userId="u-2" name="Anna Kowalska" />);

    await userEvent.click(screen.getByRole("button", { name: "forgetNamed" }));
    const dialog = await screen.findByRole("dialog");

    expect(within(dialog).getByRole("button", { name: "forgetAction" })).toBeDisabled();
    expect(mutateAsync).not.toHaveBeenCalled();
  });

  it("is inert while the erasure runs", () => {
    pending = true;
    render(<ForgetMemberMemory userId="u-2" name="Anna Kowalska" />);

    expect(screen.getByRole("button", { name: "forgetNamed" })).toBeDisabled();
  });
});
