import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { useState } from "react";
import { useOrgStore } from "@/stores";
import { phoneSettings } from "@/test-utils/phone";
import { PhoneSettings } from "./phone-settings";
vi.mock("@/hooks/use-permissions", () => ({ usePermissions: () => ({ can: () => false }) }));
vi.mock("@/hooks/use-phone", () => ({
  usePhoneSettings: () => ({
    data: phoneSettings,
    isLoading: false,
    refetch: vi.fn(),
    saveContact: { mutate: vi.fn() },
    call: { mutate: vi.fn() },
    configure: { mutate: vi.fn() },
  }),
  usePhoneCalls: () => ({ data: [], isLoading: false, refetch: vi.fn() }),
}));
vi.mock("./phone-contact", () => ({ PhoneContactForm: () => null }));
vi.mock("./phone-dialer", () => ({
  PhoneDialer: () => {
    const [text, setText] = useState("");
    return <input aria-label="report" value={text} onChange={(e) => setText(e.target.value)} />;
  },
}));
it("clears unsent private phone setup when switching organization", async () => {
  useOrgStore.setState({ activeOrgId: "first" });
  render(<PhoneSettings />);
  await userEvent.type(screen.getByRole("textbox", { name: "report" }), "Private first-org report");
  act(() => useOrgStore.setState({ activeOrgId: "second" }));
  expect(screen.getByRole("textbox", { name: "report" })).toHaveValue("");
});
