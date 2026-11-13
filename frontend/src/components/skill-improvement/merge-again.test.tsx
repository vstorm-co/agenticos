import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-error";
import { skillSession } from "@/test-utils/skill-improvement";
import { MergeAgain } from "./merge-again";

const push = vi.fn();
vi.mock("next/navigation", async (original) => ({
  ...(await original<typeof import("next/navigation")>()),
  useRouter: () => ({ push }),
}));
const discard = vi.hoisted(() => ({ mutateAsync: vi.fn(), isPending: false }));
vi.mock("@/hooks/use-improvements", () => ({ useImprovement: () => ({ discard }) }));

beforeEach(() => {
  vi.clearAllMocks();
  discard.mutateAsync.mockResolvedValue(undefined);
});

describe("MergeAgain", () => {
  it("discards the stale merge, then starts a new one on the same fork", async () => {
    render(<MergeAgain session={skillSession({ purpose: "to_main", source_fork_id: "f1" })} />);
    expect(
      screen.getByText(
        "The fork or main has a newer version than this merge read, so it is not checked again.",
      ),
    ).toBeVisible();

    await userEvent.click(
      screen.getByRole("button", { name: "Discard this merge and start again" }),
    );

    expect(discard.mutateAsync).toHaveBeenCalledOnce();
    expect(push).toHaveBeenCalledWith("/skills/k1/improve/new?fork=f1&merge=to_main");
  });

  it("stays put and says why when the merge cannot be discarded", async () => {
    discard.mutateAsync.mockRejectedValue(new ApiError(409, "The session moved on"));
    render(<MergeAgain session={skillSession({ purpose: "catch_up", fork_id: "f2" })} />);

    await userEvent.click(
      screen.getByRole("button", { name: "Discard this merge and start again" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("The session moved on");
    expect(push).not.toHaveBeenCalled();
  });

  it("offers nothing to press to a reader who may not discard the session", () => {
    render(
      <MergeAgain
        session={skillSession({ purpose: "catch_up", fork_id: "f2", can_discard: false })}
      />,
    );
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
