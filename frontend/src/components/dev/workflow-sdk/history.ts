/**
 * A bounded undo/redo stack of immutable snapshots.
 *
 * The SDK has no history. It exposes a change tracker meant to feed one, and the
 * demo app's plugin is an Overflow premium feature outside the npm package, so
 * this is our own: a pure stack here, and a store subscription in
 * `use-editor-history.tsx`.
 */
export class History<T> {
  private past: T[] = [];
  private future: T[] = [];
  private present: T | null = null;

  constructor(private readonly limit = 100) {}

  /** Start over from `snapshot`. Called after a load, which is not an undoable edit. */
  reset(snapshot: T): void {
    this.past = [];
    this.future = [];
    this.present = snapshot;
  }

  /** Record a new state. Drops the redo branch. */
  record(snapshot: T): void {
    if (this.present !== null) this.past.push(this.present);
    if (this.past.length > this.limit) this.past.shift();
    this.present = snapshot;
    this.future = [];
  }

  undo(): T | null {
    const previous = this.past.pop();
    if (previous === undefined || this.present === null) return null;
    this.future.push(this.present);
    this.present = previous;
    return previous;
  }

  redo(): T | null {
    const next = this.future.pop();
    if (next === undefined || this.present === null) return null;
    this.past.push(this.present);
    this.present = next;
    return next;
  }

  get canUndo(): boolean {
    return this.past.length > 0;
  }

  get canRedo(): boolean {
    return this.future.length > 0;
  }

  get size(): number {
    return this.past.length;
  }
}
