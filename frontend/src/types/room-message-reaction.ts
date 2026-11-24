export interface RoomMessageReactionSummary {
  emoji: string;
  count: number;
  reacted_by_me: boolean;
}

export interface RoomMessageReactionsRead {
  reactions: RoomMessageReactionSummary[];
}
