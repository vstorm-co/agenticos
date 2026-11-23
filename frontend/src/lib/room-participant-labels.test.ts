import { describe, expect, it } from "vitest";

import type { RoomParticipantRead } from "@/types/room";
import { roomParticipantIdentitySuffix } from "./room-participant-labels";

function participant(kind: "user" | "agent", id: string, name: string): RoomParticipantRead {
  return {
    kind,
    id,
    name,
    avatar_url: null,
    is_member: true,
    can_add: false,
    can_mention: true,
    auto_reply: false,
  };
}

describe("room participant duplicate labels", () => {
  it("adds no suffix to unique names or same names of different kinds", () => {
    const person = participant("user", "person-1234", "Alex");
    const agent = participant("agent", "agent-5678", "Alex");
    const unique = participant("user", "person-2468", "Riley");
    const candidates = [person, agent, unique];

    expect(roomParticipantIdentitySuffix(person, candidates)).toBeNull();
    expect(roomParticipantIdentitySuffix(agent, candidates)).toBeNull();
    expect(roomParticipantIdentitySuffix(unique, candidates)).toBeNull();
  });

  it("uses a short id tail for same-kind duplicate names", () => {
    const first = participant("user", "person-1234", "Alex");
    const second = participant("user", "person-5678", "Alex");
    const candidates = [first, second];

    expect(roomParticipantIdentitySuffix(first, candidates)).toBe("1234");
    expect(roomParticipantIdentitySuffix(second, candidates)).toBe("5678");
  });

  it("extends the suffix when duplicate ids share their last four characters", () => {
    const first = participant("agent", "agent-a1234", "Writer");
    const second = participant("agent", "agent-b1234", "Writer");
    const candidates = [first, second];

    expect(roomParticipantIdentitySuffix(first, candidates)).toBe("a1234");
    expect(roomParticipantIdentitySuffix(second, candidates)).toBe("b1234");
  });
});
