import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ForkedFrom } from "./forked-from";

describe("ForkedFrom", () => {
  it("names the source and opens it", async () => {
    const onOpen = vi.fn();
    render(
      <ForkedFrom
        origin={{ conversation_id: "c-1", message_id: "m-1", title: "Pricing" }}
        onOpen={onOpen}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Pricing" }));

    expect(screen.getByText(/Forked from/)).toBeInTheDocument();
    expect(onOpen).toHaveBeenCalledWith("c-1");
  });

  it("names a source with no title as untitled", () => {
    render(
      <ForkedFrom
        origin={{ conversation_id: "c-1", message_id: null, title: null }}
        onOpen={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Untitled conversation" })).toBeInTheDocument();
  });
});
