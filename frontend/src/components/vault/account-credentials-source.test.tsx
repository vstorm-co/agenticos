import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import { LOGO_DATA_URI } from "@/lib/logo.generated";
import { AccountCredentialsSource } from "./account-credentials-source";

it("shows the canonical AgenticOS mark and lets the user change the connection method", async () => {
  const onChange = vi.fn();
  render(<AccountCredentialsSource value="own" available locked={false} onChange={onChange} />);
  expect(screen.getByAltText("")).toHaveAttribute("src", LOGO_DATA_URI);
  const managed = screen.getByRole("radio", { name: /Continue with AgenticOS/ });
  await userEvent.click(managed);
  expect(onChange).toHaveBeenCalledWith("agenticos");
  expect(managed).toHaveClass("sr-only");
});

it("explains where tokens go when the shared application is selected", () => {
  render(
    <AccountCredentialsSource value="agenticos" available locked={false} onChange={vi.fn()} />,
  );
  expect(screen.getByText(/Tokens are exchanged through our bridge/)).toBeInTheDocument();
  expect(screen.getByRole("radio", { name: /Continue with AgenticOS/ })).toBeChecked();
});

it("keeps an unavailable managed account locked during repair", () => {
  render(
    <AccountCredentialsSource value="agenticos" available={false} locked onChange={vi.fn()} />,
  );
  for (const radio of screen.getAllByRole("radio")) expect(radio).toBeDisabled();
  expect(screen.getByText("Not available on this deployment yet.")).toBeInTheDocument();
});

it("does not offer shared connections on an unapproved deployment", () => {
  render(
    <AccountCredentialsSource value="own" available={false} locked={false} onChange={vi.fn()} />,
  );
  expect(screen.queryByRole("radio")).not.toBeInTheDocument();
  expect(screen.queryByText(/Continue with AgenticOS/)).not.toBeInTheDocument();
});
