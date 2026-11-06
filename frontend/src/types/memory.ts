/** What erasing memory removed. */
export interface MemoryErasureResult {
  notes_deleted: number;
  /** Recorded claims erased with the notes, copies shared out of them included. */
  claims_deleted?: number;
}
