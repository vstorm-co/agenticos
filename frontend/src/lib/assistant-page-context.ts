import { pageOf } from "@/lib/assistant-bubbles";

/** Reference data for one question; it never grants access to a named resource. */
export interface AssistantPageContext {
  path: string;
  title: string;
  captured_at: string;
  resource?: { kind: string; id: string; title?: string };
  view?: string;
  filters?: Record<string, string>;
  selected_ids?: string[];
  summary?: string;
  selected_text?: string;
}

/** Explicit details supplied by a page; no DOM, form or query-string capture. */
export type AssistantPageDetails = Omit<AssistantPageContext, "path" | "captured_at" | "title"> & {
  title?: string;
};

const record = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);

function text(value: unknown, limit: number): string | undefined {
  return typeof value === "string" && value.trim() ? value.slice(0, limit) : undefined;
}

/** Keep the route only. Origins, query values and fragments never accompany it. */
export function assistantPagePath(pathname: string): string {
  const path = pageOf(pathname.split(/[?#]/, 1)[0] ?? "/");
  if (!path.startsWith("/") || path.startsWith("//") || /[\\\\\u0000-\u001f\u007f]/.test(path))
    return "/";
  return path.slice(0, 2048);
}

/** Copy only bounded fields in the server contract; ignore everything else. */
export function sanitizeAssistantPageDetails(value: unknown): AssistantPageDetails {
  if (!record(value)) return {};
  const details: AssistantPageDetails = {};
  const title = text(value.title, 240);
  if (title) details.title = title;
  if (record(value.resource)) {
    const kind = text(value.resource.kind, 64);
    const id = text(value.resource.id, 128);
    const resourceTitle = text(value.resource.title, 240);
    if (kind && id)
      details.resource = { kind, id, ...(resourceTitle ? { title: resourceTitle } : {}) };
  }
  const view = text(value.view, 120);
  if (view) details.view = view;
  if (record(value.filters)) {
    const filters = Object.entries(value.filters)
      .filter(
        ([key, field]) =>
          !!key.trim() &&
          key.length <= 80 &&
          !/password|secret|token|authorization|cookie|api[-_]?key|^(__proto__|constructor|prototype)$/i.test(
            key,
          ) &&
          typeof field === "string",
      )
      .slice(0, 20)
      .map(([key, field]) => [key, (field as string).slice(0, 240)]);
    if (filters.length) details.filters = Object.fromEntries(filters);
  }
  if (Array.isArray(value.selected_ids)) {
    const selected = value.selected_ids
      .filter((id): id is string => typeof id === "string" && !!id.trim())
      .slice(0, 20)
      .map((id) => id.slice(0, 128));
    if (selected.length) details.selected_ids = selected;
  }
  const summary = text(value.summary, 6000);
  if (summary) details.summary = summary;
  const selectedText = text(value.selected_text, 2000);
  if (selectedText) details.selected_text = selectedText;
  return details;
}

/** Detached snapshot, made at submission rather than when the window opens. */
export function assistantPageSnapshot(
  pathname: string,
  documentTitle: string,
  registered?: AssistantPageDetails,
): AssistantPageContext {
  const path = assistantPagePath(pathname);
  const details = sanitizeAssistantPageDetails(registered);
  return {
    path,
    title: details.title || text(documentTitle, 240) || path.slice(0, 240),
    captured_at: new Date().toISOString(),
    ...details,
  };
}
