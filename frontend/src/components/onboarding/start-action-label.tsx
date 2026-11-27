/** Keep concise visual actions on phones without shortening their accessible name. */
export function StartActionLabel({ full, short }: { full: string; short: string }) {
  return (
    <>
      <span className="sr-only">{full}</span>
      <span aria-hidden className="sm:hidden">
        {short}
      </span>
      <span aria-hidden className="hidden sm:inline">
        {full}
      </span>
    </>
  );
}
