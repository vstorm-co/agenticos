import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { phoneSettings, phoneContact } from "@/test-utils/phone";
import { PhoneContactForm } from "./phone-contact";
vi.mock("@/hooks/use-agents", () => ({
  useAgents: () => ({ agents: [{ id: "agent", name: "Tracker" }] }),
}));
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

it("requires an explicit agent and importance criteria before important-case consent", async () => {
  const save = vi.fn();
  render(<PhoneContactForm settings={phoneSettings} pending={false} onSave={save} />);
  await userEvent.click(screen.getByRole("combobox", { name: "Verified SMS number" }));
  await userEvent.click(screen.getByRole("option", { name: "••••1111" }));
  await userEvent.click(
    screen.getByRole("checkbox", { name: "Allow these agents to call about important open cases" }),
  );
  expect(screen.getByRole("button", { name: "Save phone consent" })).toBeDisabled();
  await userEvent.click(screen.getByRole("checkbox", { name: "Tracker" }));
  await userEvent.type(
    screen.getByRole("textbox", { name: "What counts as important" }),
    "Production outages only",
  );
  await userEvent.clear(screen.getByRole("spinbutton", { name: /Wait after/ }));
  await userEvent.type(screen.getByRole("spinbutton", { name: /Wait after/ }), "600");
  await userEvent.click(screen.getByRole("button", { name: "Save phone consent" }));
  expect(save).toHaveBeenCalledWith(
    expect.objectContaining({
      agent_ids: ["agent"],
      allow_important: true,
      importance_instructions: "Production outages only",
      escalation_delay_seconds: 600,
    }),
  );
});

it("lets the person remove a deleted agent and revoke call consent", async () => {
  const save = vi.fn();
  render(
    <PhoneContactForm
      settings={{
        ...phoneSettings,
        contact: {
          ...phoneContact,
          id: "contact",
          masked_number: "••••1111",
          allow_calls: true,
          agent_ids: ["deleted-agent"],
        },
      }}
      pending={false}
      onSave={save}
    />,
  );
  await userEvent.click(
    screen.getByRole("checkbox", { name: "Unavailable agent (deleted-agent)" }),
  );
  await userEvent.click(screen.getByRole("checkbox", { name: "Allow calls to my number" }));
  await userEvent.click(screen.getByRole("button", { name: "Save phone consent" }));
  expect(save).toHaveBeenCalledWith(expect.objectContaining({ agent_ids: [], allow_calls: false }));
});

it("saves language, daily limits and local quiet hours explicitly", async () => {
  const save = vi.fn();
  render(<PhoneContactForm settings={phoneSettings} pending={false} onSave={save} />);
  for (const [label, choice] of [
    ["Verified SMS number", "••••1111"],
    ["Spoken report language", "Polski"],
    ["Quiet hours start", "21:00"],
    ["Quiet hours end", "09:00"],
  ]) {
    await userEvent.click(screen.getByRole("combobox", { name: label }));
    await userEvent.click(screen.getByRole("option", { name: choice }));
  }
  await userEvent.clear(screen.getByRole("textbox", { name: "Time zone (IANA)" }));
  await userEvent.type(screen.getByRole("textbox", { name: "Time zone (IANA)" }), "Europe/Warsaw");
  await userEvent.clear(screen.getByRole("spinbutton", { name: "Calls per rolling 24 hours" }));
  await userEvent.type(screen.getByRole("spinbutton", { name: "Calls per rolling 24 hours" }), "5");
  await userEvent.click(screen.getByRole("button", { name: "Save phone consent" }));
  expect(save).toHaveBeenCalledWith(
    expect.objectContaining({
      report_language: "pl-PL",
      timezone: "Europe/Warsaw",
      calls_per_day: 5,
      quiet_start_hour: 21,
      quiet_end_hour: 9,
    }),
  );
});
