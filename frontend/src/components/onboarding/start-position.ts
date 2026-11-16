/** A tab's place in the walkthrough, not evidence of completion or saved edits. */
export function rememberStartPosition(step: string, organizationId: string | null): void {
  const url = new URL(window.location.href);
  url.searchParams.set("start-step", step);
  url.searchParams.delete("question");
  if (organizationId) url.searchParams.set("workspace", organizationId);
  else url.searchParams.delete("workspace");
  // Next copies its router state itself; passing its internal marker would skip URL synchronization.
  window.history.replaceState(null, "", url);
}

/** Hidden or stale steps must not replace the active organization's URL. */
export function rememberStartQuestion(
  step: string,
  organizationId: string,
  question: string,
): void {
  const url = new URL(window.location.href);
  if (
    url.searchParams.get("start-step") !== step ||
    url.searchParams.get("workspace") !== organizationId ||
    url.searchParams.get("question") === question
  )
    return;
  url.searchParams.set("question", question);
  window.history.replaceState(null, "", url);
}
