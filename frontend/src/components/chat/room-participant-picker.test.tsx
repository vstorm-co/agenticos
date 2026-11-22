import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import messages from "@/../messages/en.json";
import type { RoomParticipantRead } from "@/types/room";
import { RoomParticipantPicker } from "./room-participant-picker";

function participant(
  id: string,
  name: string,
  kind: "user" | "agent" = "agent",
): RoomParticipantRead {
  return {
    kind,
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

  it("groups people and agents, ignores selection while disabled and explains an empty search", async () => {
    const onAdd = vi.fn();
    const user = userEvent.setup();
    render(
      <NextIntlClientProvider locale="en" messages={messages}>
        <RoomParticipantPicker
          candidates={[participant("user-1", "Morgan", "user"), participant("agent-1", "Writer")]}
          disabled
          onAdd={onAdd}
        />
      </NextIntlClientProvider>,
    );

    expect(screen.getByText("People")).toBeVisible();
    expect(screen.getByText("Agents")).toBeVisible();
    await user.click(screen.getByRole("option", { name: "Morgan, People, Add people or agents" }));
    expect(onAdd).not.toHaveBeenCalled();

    await user.type(screen.getByRole("combobox"), "zzz");
    expect(screen.getByText("No matching people or agents.")).toBeVisible();
  });

  it("says nobody can be added when there are no candidates", () => {
    render(
      <NextIntlClientProvider locale="en" messages={messages}>
        <RoomParticipantPicker candidates={[]} disabled={false} onAdd={vi.fn()} />
      </NextIntlClientProvider>,
    );

    expect(screen.getByText("No people or agents can be added.")).toBeVisible();
  });
});
