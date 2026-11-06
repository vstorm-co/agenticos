import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { phoneSettings } from "@/test-utils/phone";
import { PhoneRouting } from "./phone-routing";

it("lets an operator remove a transfer contact that is no longer available", async () => {
  const save = vi.fn();
  render(
    <PhoneRouting
      settings={{
        ...phoneSettings,
        endpoints: [
          {
            id: "endpoint",
            bot_id: "bot",
            bot_name: "Telephone",
            inbound_url: "https://phone.example/inbound",
            status_url: "https://phone.example/status",
            enabled: true,
            inbound_embed_id: null,
            max_call_seconds: 300,
            calls_per_hour: 10,
            calls_per_day: 30,
            max_concurrent: 2,
            daily_budget_usd: 5,
            price_per_minute_usd: 0.1,
            transfer_contact_ids: ["retired-contact"],
          },
        ],
      }}
      pending={false}
      onSave={save}
    />,
  );
  await userEvent.click(screen.getByRole("combobox", { name: "Twilio SMS bot" }));
  await userEvent.click(screen.getByRole("option", { name: "Telephone" }));
  await userEvent.click(
    screen.getByRole("checkbox", { name: "Unavailable transfer contact (retired-contact)" }),
  );
  await userEvent.click(screen.getByRole("button", { name: "Save telephone routing" }));
  expect(save).toHaveBeenCalledWith("bot", expect.objectContaining({ transfer_contact_ids: [] }));
});

it("configures a new route with explicit limits, inbound exposure and transfer consent", async () => {
  const save = vi.fn();
  render(
    <PhoneRouting
      settings={{
        ...phoneSettings,
        public_voice_embeds: [{ id: "voice", label: "Public voice" }],
        transfer_contacts: [{ id: "contact", label: "On-call" }],
      }}
      pending={false}
      onSave={save}
    />,
  );
  await userEvent.click(screen.getByRole("combobox", { name: "Twilio SMS bot" }));
  await userEvent.click(screen.getByRole("option", { name: "Telephone" }));
  await userEvent.click(screen.getByRole("checkbox", { name: "Enable telephone routing" }));
  const fields = screen.getAllByRole("spinbutton");
  for (const field of fields) {
    await userEvent.clear(field);
    await userEvent.type(field, "1");
  }
  await userEvent.clear(fields[0]!);
  await userEvent.type(fields[0]!, "120");
  await userEvent.click(screen.getByRole("checkbox", { name: "On-call" }));
  await userEvent.click(
    screen.getByRole("combobox", { name: "Public voice page or widget for inbound calls" }),
  );
  await userEvent.click(screen.getByRole("option", { name: "Public voice" }));
  await userEvent.click(screen.getByRole("button", { name: "Save telephone routing" }));
  expect(save).toHaveBeenCalledWith(
    "bot",
    expect.objectContaining({
      enabled: true,
      inbound_embed_id: "voice",
      max_call_seconds: 120,
      transfer_contact_ids: ["contact"],
    }),
  );
});
