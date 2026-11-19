import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import messages from "@/../messages/en.json";
import type { RoomParticipantRead } from "@/types/room";
import { RoomMentionPalette } from "./room-mention-palette";

function participant(id: string, name: string): RoomParticipantRead {
  return {
    kind: "user",
    id,
    name,
    avatar_url: null,
    is_member: true,
    can_add: false,
    can_mention: true,
    auto_reply: false,
  };
}

describe("RoomMentionPalette", () => {
  it("adds accessible short identity suffixes only to same-kind duplicate names", () => {
    render(
      <NextIntlClientProvider locale="en" messages={messages}>
        <RoomMentionPalette
          id="room-mention-list"
          items={[
            participant("person-1234", "Alex"),
            participant("person-5678", "Alex"),
            participant("person-9012", "Riley"),
          ]}
          selectedIndex={-1}
          onSelectIndex={vi.fn()}
          onPick={vi.fn()}
          onRetry={vi.fn()}
          isLoading={false}
          failed={false}
        />
      </NextIntlClientProvider>,
    );

    expect(screen.getByRole("option", { name: "Alex · 1234, People" })).toBeVisible();
    expect(screen.getByRole("option", { name: "Alex · 5678, People" })).toBeVisible();
    expect(screen.getByText("· 1234")).toBeVisible();
    expect(screen.getByText("· 5678")).toBeVisible();
    expect(screen.getByRole("option", { name: "Riley, People" })).toBeVisible();
  });
});
