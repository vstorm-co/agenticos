import type { RoomParticipantRead } from "@/types/room";

/** Return a short id tail only when peers of the same kind share this visible name. */
export function roomParticipantIdentitySuffix(
  participant: RoomParticipantRead,
  participants: readonly RoomParticipantRead[],
): string | null {
  const duplicates = participants.filter(
    (candidate) =>
      candidate.kind === participant.kind &&
      candidate.name === participant.name &&
      candidate.id !== participant.id,
  );
  if (duplicates.length === 0) return null;

  const id = participant.id;
  let length = Math.min(4, id.length);
  while (
    length < id.length &&
    duplicates.some(
      (candidate) => candidate.id.slice(-length).toLowerCase() === id.slice(-length).toLowerCase(),
    )
  ) {
    length++;
  }
  return id.slice(-length);
}
