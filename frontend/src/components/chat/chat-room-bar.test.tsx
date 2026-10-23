import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ChatRoomBar } from "./chat-room-bar";
import type { ChatPerson } from "@/types";

vi.mock("./share-dialog", () => ({
  ShareDialog: ({ open }: { open: boolean }) => (open ? <div role="dialog">share</div> : null),
}));

function person(id: string, name: string): ChatPerson {
  return { user_id: id, name, has_avatar: false, avatar_color: null };
}

const ME = person("me", "Kacper");

describe("ChatRoomBar", () => {
  it("draws nothing for a chat the reader has to themselves", () => {
    const { container } = render(
      <ChatRoomBar conversationId="c-1" present={[ME]} meId="me" canShare />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("names the one other person here, and lets the owner invite more", async () => {
    render(
      <ChatRoomBar conversationId="c-1" present={[ME, person("a", "Anna")]} meId="me" canShare />,
    );
    expect(screen.getByText("Anna is here too")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Invite" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("counts a crowd past its faces, and offers no invite to a guest", () => {
    const crowd = ["Anna", "Ola", "Piotr", "Ewa", "Jan"].map((name) => person(name, name));
    render(
      <ChatRoomBar conversationId="c-1" present={[ME, ...crowd]} meId="me" canShare={false} />,
    );

    expect(screen.getByText("5 people are here with you")).toBeInTheDocument();
    expect(screen.getByText("+1")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Invite" })).toBeNull();
  });
});
