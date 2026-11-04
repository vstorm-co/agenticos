import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { BrowserNavigation } from "./browser-navigation";

function setup(holding = true, url: string | null = "https://example.test/old") {
  const send = vi.fn();
  const result = render(<BrowserNavigation holding={holding} url={url} send={send} />);
  return { ...result, send, input: screen.getByRole("textbox", { name: "Website address" }) };
}

describe("browser navigation", () => {
  it("navigates the held tab on Enter and supplies HTTPS for a bare host", () => {
    const { input, send } = setup();
    fireEvent.change(input, { target: { value: "docs.example.test/guide" } });
    fireEvent.submit(input.closest("form")!);
    expect(send).toHaveBeenCalledWith({ type: "navigate", url: "https://docs.example.test/guide" });
  });

  it.each([
    "javascript:alert(1)",
    "file:///etc/passwd",
    "https://user:pass@example.test/",
    "https://",
    "https://example.test:0/",
    "",
  ])("refuses an invalid or credential-bearing address: %s", (value) => {
    const { input, send } = setup();
    fireEvent.change(input, { target: { value } });
    fireEvent.click(screen.getByRole("button", { name: "Go" }));
    expect(send).not.toHaveBeenCalled();
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("alert")).toHaveTextContent("Enter an HTTP or HTTPS website address.");
    fireEvent.change(input, { target: { value: "https://example.test/valid" } });
    expect(input).toHaveAttribute("aria-invalid", "false");
  });

  it("sends back, forward and reload commands", () => {
    const { send } = setup();
    for (const name of ["Back", "Forward", "Reload"])
      fireEvent.click(screen.getByRole("button", { name }));
    expect(send.mock.calls.map(([command]) => command)).toEqual([
      { type: "back" },
      { type: "forward" },
      { type: "reload" },
    ]);
  });

  it("shows the latest location without overwriting an address being edited", () => {
    const { input, rerender, send } = setup();
    rerender(<BrowserNavigation holding url="https://example.test/new" send={send} />);
    expect(input).toHaveValue("https://example.test/new");
    fireEvent.change(input, { target: { value: "https://draft.test/" } });
    rerender(<BrowserNavigation holding url="https://example.test/redirect" send={send} />);
    expect(input).toHaveValue("https://draft.test/");
  });

  it("cannot drive a browser somebody else holds", () => {
    const { input, send } = setup(false);
    expect(input).toHaveAttribute("readonly");
    fireEvent.submit(input.closest("form")!);
    expect(send).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Back" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Go" })).toBeNull();
  });

  it("can reload the current address without editing and handles an empty location", () => {
    const { input, send, rerender } = setup();
    fireEvent.click(screen.getByRole("button", { name: "Go" }));
    expect(send).toHaveBeenCalledWith({ type: "navigate", url: "https://example.test/old" });
    rerender(<BrowserNavigation holding url={null} send={send} />);
    expect(input).toHaveValue("");
    fireEvent.submit(input.closest("form")!);
    expect(send).toHaveBeenCalledTimes(1);
    rerender(<BrowserNavigation holding={false} url={null} send={send} />);
    expect(input).toHaveValue("");
  });
});

it.each([
  ["localhost:3000", "https://localhost:3000/"],
  ["example.com:8080/path", "https://example.com:8080/path"],
])("accepts a bare host with a port: %s", (value, expected) => {
  const { input, send } = setup();
  fireEvent.change(input, { target: { value } });
  fireEvent.submit(input.closest("form")!);
  expect(send).toHaveBeenCalledWith({ type: "navigate", url: expected });
});
