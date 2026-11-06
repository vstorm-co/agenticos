import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { useState } from "react";
import { useOrgStore } from "@/stores";
import { phoneSettings, phoneCall, phoneContact } from "@/test-utils/phone";
import { PhoneSettings } from "./phone-settings";
import type { PhoneContactConfig, PhoneEndpointConfig, PhoneCallCreate } from "@/lib/phone-api";

const state = vi.hoisted(() => ({
  loading: false,
  error: null as Error | null,
  callsLoading: false,
  callsError: null as Error | null,
  hasCall: false,
  canManage: false,
  hasSettings: true,
  refresh: vi.fn(),
  refreshCalls: vi.fn(),
  save: vi.fn(),
  call: vi.fn(),
  configure: vi.fn(),
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: () => state.canManage }),
}));
vi.mock("@/hooks/use-phone", () => ({
  usePhoneSettings: () => ({
    data: state.hasSettings ? phoneSettings : undefined,
    error: state.error,
    isLoading: state.loading,
    refetch: state.refresh,
    saveContact: { mutate: state.save },
    call: { mutate: state.call },
    configure: { mutate: state.configure },
  }),
  usePhoneCalls: () => ({
    data: state.hasCall ? [phoneCall] : [],
    error: state.callsError,
    isLoading: state.callsLoading,
    refetch: state.refreshCalls,
  }),
}));
vi.mock("./phone-contact", () => ({
  PhoneContactForm: ({ onSave }: { onSave: (data: PhoneContactConfig) => void }) => (
    <button onClick={() => onSave(phoneContact)}>save consent</button>
  ),
}));
vi.mock("./phone-routing", () => ({
  PhoneRouting: ({ onSave }: { onSave: (id: string, data: PhoneEndpointConfig) => void }) => (
    <button
      onClick={() =>
        onSave("bot", {
          enabled: true,
          inbound_embed_id: null,
          max_call_seconds: 60,
          calls_per_hour: 2,
          calls_per_day: 3,
          max_concurrent: 1,
          daily_budget_usd: 5,
          price_per_minute_usd: 0.1,
          transfer_contact_ids: [],
        })
      }
    >
      save routing
    </button>
  ),
}));
vi.mock("./phone-call-card", () => ({ PhoneReceiptCard: () => <p>call receipt</p> }));
vi.mock("./phone-dialer", () => ({
  PhoneDialer: ({ onCall }: { onCall: (data: PhoneCallCreate) => void }) => {
    const [text, setText] = useState("");
    return (
      <>
        <input aria-label="report" value={text} onChange={(e) => setText(e.target.value)} />
        <button
          onClick={() =>
            onCall({
              request_key: "request",
              endpoint_id: "endpoint",
              mode: "report",
              report: text,
            })
          }
        >
          call
        </button>
      </>
    );
  },
}));
beforeEach(() => {
  vi.clearAllMocks();
  Object.assign(state, {
    loading: false,
    error: null,
    callsLoading: false,
    callsError: null,
    hasCall: false,
    canManage: false,
    hasSettings: true,
  });
  useOrgStore.setState({ activeOrgId: "first" });
});
it("clears unsent private phone setup when switching organization", async () => {
  render(<PhoneSettings />);
  await userEvent.type(screen.getByRole("textbox", { name: "report" }), "Private first-org report");
  act(() => useOrgStore.setState({ activeOrgId: "second" }));
  expect(screen.getByRole("textbox", { name: "report" })).toHaveValue("");
});
it("offers retry after settings or call reads fail", async () => {
  state.error = new Error("Unavailable");
  const { rerender } = render(<PhoneSettings />);
  await userEvent.click(screen.getByRole("button", { name: "Refresh" }));
  expect(state.refresh).toHaveBeenCalled();
  state.error = null;
  state.callsError = new Error("Calls unavailable");
  rerender(<PhoneSettings />);
  await userEvent.click(screen.getAllByRole("button", { name: "Refresh" })[0]!);
  expect(state.refreshCalls).toHaveBeenCalled();
});
it("keeps loading and missing-settings states distinct", () => {
  state.loading = true;
  const { rerender } = render(<PhoneSettings />);
  expect(screen.getByText(/Loading/)).toBeVisible();
  state.loading = false;
  state.hasSettings = false;
  rerender(<PhoneSettings />);
  expect(screen.getByRole("button", { name: "Refresh" })).toBeVisible();
});
it("gates administration and forwards only reviewed routing", async () => {
  const { rerender } = render(<PhoneSettings administration />);
  expect(screen.queryByText("save routing")).not.toBeInTheDocument();
  expect(screen.queryByText("save consent")).not.toBeInTheDocument();
  state.canManage = true;
  rerender(<PhoneSettings administration />);
  await userEvent.click(screen.getByRole("button", { name: "save routing" }));
  expect(state.configure).toHaveBeenCalledWith({
    botId: "bot",
    data: expect.objectContaining({ enabled: true }),
  });
});
it("keeps report text until a call is accepted, then clears it", async () => {
  state.call.mockImplementation((_data, options) => options.onSuccess());
  state.hasCall = true;
  render(<PhoneSettings />);
  expect(screen.getByText("call receipt")).toBeVisible();
  await userEvent.type(screen.getByRole("textbox", { name: "report" }), "Ready");
  await userEvent.click(screen.getByRole("button", { name: "call" }));
  expect(state.call).toHaveBeenCalledWith(
    expect.objectContaining({ report: "Ready" }),
    expect.anything(),
  );
  expect(screen.getByRole("textbox", { name: "report" })).toHaveValue("");
  await userEvent.click(screen.getByRole("button", { name: "save consent" }));
  expect(state.save).toHaveBeenCalledWith(phoneContact);
  await userEvent.click(screen.getByRole("button", { name: "Refresh" }));
  expect(state.refresh).toHaveBeenCalled();
  expect(state.refreshCalls).toHaveBeenCalled();
});
