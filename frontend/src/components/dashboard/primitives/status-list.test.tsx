import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { StatusList } from "./status-list";

describe("StatusList", () => {
  afterEach(() => vi.restoreAllMocks());

  it("keeps two rows with the same label apart by their ids", () => {
    // Two channel bots may share a name; keying on it made React drop or
    // duplicate one and warn about a repeated key.
    const error = vi.spyOn(console, "error").mockImplementation(() => {});

    render(
      <StatusList
        rows={[
          { id: "bot-1", label: "test", pill: "Polling", tone: "ok" },
          { id: "bot-2", label: "test", pill: "Webhook", tone: "ok" },
        ]}
      />,
    );

    expect(screen.getAllByText("test")).toHaveLength(2);
    expect(error).not.toHaveBeenCalledWith(
      expect.stringContaining("Encountered two children with the same key"),
      expect.anything(),
      expect.anything(),
    );
    expect(error.mock.calls.flat().join(" ")).not.toContain("same key");
  });
});
