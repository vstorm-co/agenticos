/**
 * A bounded undo/redo stack of immutable snapshots.
 *
 * The SDK has no history. It exposes a change tracker meant to feed one, and the
 * demo app's plugin is an Overflow premium feature outside the npm package, so
 * this is our own: a pure stack and its debounced recorder here, and the store
 * subscription that feeds them in `editor-controller.tsx`.
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

/**
 * Turns a stream of store changes into history entries, one per gesture.
 *
 * A drag emits a change per frame, so a change is recorded only once it has been
 * quiet for `delayMs`. Undo and redo must call `flush` first: a change still inside
 * that window is not in the stack yet, and undoing past it would skip a step and
 * leave the change impossible to redo.
 */
export class Recorder<T> {
  private timer: ReturnType<typeof setTimeout> | undefined;
  private lastKey = "";

  constructor(
    private readonly history: History<T>,
    private readonly read: () => { key: string; snapshot: T },
    private readonly delayMs = 250,
  ) {}

  /** The state as loaded, which is not an edit. */
  baseline(): void {
    const { key, snapshot } = this.read();
    this.history.reset(snapshot);
    this.lastKey = key;
  }

  /** A change happened; record it once things go quiet. */
  schedule(): void {
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.flush(), this.delayMs);
  }

  /** Record a pending change now, if it changed anything. */
  flush(): void {
    clearTimeout(this.timer);
    this.timer = undefined;
    const { key, snapshot } = this.read();
    if (key === this.lastKey) return;
    this.lastKey = key;
    this.history.record(snapshot);
  }

  /** The state was set by undo or redo, so it is already in the stack. */
  restored(key: string): void {
    this.lastKey = key;
  }

  cancel(): void {
    clearTimeout(this.timer);
    this.timer = undefined;
  }
}
