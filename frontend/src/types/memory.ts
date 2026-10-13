/**
 * What erasing memory removed.
 *
 * Two counts rather than one, because the two halves are different systems and
 * can fail independently: the notes are rows in this deployment, the mem0
 * memories are somebody else's service. Telling somebody their memory is gone
 * when half of it is not is the failure this reports rather than hides.
 */
export interface MemoryErasureResult {
  notes_deleted: number;
  mem0_agents_cleared: number;
}
