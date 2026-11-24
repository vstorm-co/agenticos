/**
 * The yellow dot that marks where something waits for the reader, set on the
 * corner of the icon it sits beside, which is drawn `relative`. Decoration only:
 * what it means is said by the control it marks.
 */
export function AttentionDot({ testId }: { testId?: string }) {
  return (
    <span
      aria-hidden
      data-testid={testId}
      className="bg-warning ring-background absolute -top-1 -right-1 size-2 rounded-full ring-2"
    />
  );
}
