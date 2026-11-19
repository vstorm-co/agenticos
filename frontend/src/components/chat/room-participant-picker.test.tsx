import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import messages from "@/../messages/en.json";
import type { RoomParticipantRead } from "@/types/room";
import { RoomParticipantPicker } from "./room-participant-picker";

function participant(id: string, name: string): RoomParticipantRead {
  return {
    kind: "agent",
    id,
    name,
    avatar_url: null,
    is_member: false,
    can_add: true,
    can_mention: false,
    auto_reply: false,
  };
}

describe("RoomParticipantPicker", () => {
  it("keeps same-kind duplicate candidates distinct and selects the requested identity", async () => {
    const onAdd = vi.fn();
    const user = userEvent.setup();
    const first = participant("agent-1234", "Writer");
    const second = participant("agent-5678", "Writer");
    render(
      <NextIntlClientProvider locale="en" messages={messages}>
        <RoomParticipantPicker candidates={[first, second]} disabled={false} onAdd={onAdd} />
      </NextIntlClientProvider>,
    );

    expect(
      screen.getByRole("option", { name: "Writer · 1234, Agents, Add people or agents" }),
    ).toBeVisible();
    expect(
      screen.getByRole("option", { name: "Writer · 5678, Agents, Add people or agents" }),
    ).toBeVisible();
    expect(screen.getByText("· 1234")).toBeVisible();
    expect(screen.getByText("· 5678")).toBeVisible();

    await user.click(
      screen.getByRole("option", { name: "Writer · 5678, Agents, Add people or agents" }),
    );
    expect(onAdd).toHaveBeenCalledWith(second);
  });
});
