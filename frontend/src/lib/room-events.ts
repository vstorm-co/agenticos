export interface RoomChange {
  conversationId: string;
  accountId: string | undefined;
  organizationId: string | null;
}

const listeners = new Set<(event: RoomChange) => void>();

/** Persisted room changes, separate from a running agent's stream. */
export function onRoomChange(listener: (event: RoomChange) => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function announceRoomChange(event: RoomChange): void {
  for (const listener of listeners) listener(event);
}
