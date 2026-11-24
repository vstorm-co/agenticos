import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";

import { CopyCode } from "./copy-code";
import { SecretRevealField } from "@/components/triggers/secret-reveal-field";

const toastError = vi.hoisted(() => vi.fn());
vi.mock("sonner", () => ({ toast: { error: toastError } }));
afterEach(() => {
  vi.restoreAllMocks();
  toastError.mockClear();
});

for (const kind of ["code", "secret"] as const) {
  it(`${kind} reports a denied clipboard and lets the user retry without losing the value`, async () => {
    const user = userEvent.setup();
    const write = vi
      .spyOn(navigator.clipboard, "writeText")
      .mockRejectedValueOnce(new DOMException("Denied", "NotAllowedError"))
      .mockResolvedValueOnce(undefined);
    if (kind === "code") render(<CopyCode code="https://api.example" />);
    else
      render(
        <SecretRevealField secret="dummy-test-secret" label="Test credential" note="Copy once" />,
      );
    await user.click(screen.getByRole("button", { name: "Copy" }));
    expect(toastError).toHaveBeenCalledWith("Copy failed");
    expect(screen.queryByRole("button", { name: "Copied" })).not.toBeInTheDocument();
    if (kind === "secret")
      expect(screen.getByLabelText("Test credential")).toHaveValue("dummy-test-secret");
    await user.click(screen.getByRole("button", { name: "Copy" }));
    expect(await screen.findByRole("button", { name: "Copied" })).toBeInTheDocument();
    expect(write).toHaveBeenLastCalledWith(
      kind === "code" ? "https://api.example" : "dummy-test-secret",
    );
  });
}
