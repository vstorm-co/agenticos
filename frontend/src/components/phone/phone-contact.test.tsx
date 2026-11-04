import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { phoneSettings } from "@/test-utils/phone";
import { PhoneContactForm } from "./phone-contact";
it("requires a selected verified identity and explicit report consent", async () => {
  const save = vi.fn();
  render(<PhoneContactForm settings={phoneSettings} pending={false} onSave={save} />);
  expect(save).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Save phone consent" })).toBeDisabled();
  await userEvent.click(screen.getByRole("combobox", { name: "Verified SMS number" }));
  await userEvent.click(screen.getByRole("option", { name: "••••1111" }));
  await userEvent.click(
    screen.getByRole("checkbox", { name: "Allow spoken reports, including playback to voicemail" }),
  );
  await userEvent.click(screen.getByRole("button", { name: "Save phone consent" }));
  expect(save).toHaveBeenCalledWith(
    expect.objectContaining({
      identity_id: "identity",
      allow_calls: false,
      allow_reports: true,
      allow_transfers: false,
      report_language: "en-US",
      quiet_start_hour: 22,
      quiet_end_hour: 8,
    }),
  );
});
it("explains why an unverified person cannot enable calls", () => {
  render(
    <PhoneContactForm
      settings={{ ...phoneSettings, sms_identities: [] }}
      pending={false}
      onSave={vi.fn()}
    />,
  );
  expect(screen.getByText(/Link and verify an SMS number/)).toBeVisible();
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});
