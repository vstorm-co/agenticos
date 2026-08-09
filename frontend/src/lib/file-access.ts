/**
 * How the viewer reaches one file, without learning where it lives.
 *
 * Four surfaces open a file and they are addressed four different ways: a workspace
 * file through its workspace's id, the same file through the conversation that holds
 * it, a knowledge base document through its collection, an attachment through the
 * files route. The authorisation differs on purpose - a chat is authorised by
 * fetching the conversation, so somebody it was shared with reaches the files, and
 * simplifying that to a workspace id would break a shared chat.
 *
 * So the address is the caller's business and the viewer takes this instead. It is
 * deliberately not a discriminated union: a `kind === "workspace"` branch inside the
 * shared component is the thing four viewers were, one indirection later.
 */

/** One file's characters. Every origin answers this shape. */
export interface FileText {
  content: string;
  /** Whether the answer was shortened. An agent still reads the whole file. */
  truncated: boolean;
}

/**
 * Everything the viewer does to a file.
 *
 * The two keys identify the two *bodies*, so a surface opening a file somebody
 * already opened paints from cache rather than fetching again. Both are needed and
 * they must not be equal: text and bytes are different answers for one path, and a
 * viewer showing a PDF must not be handed a cached string for it. They also separate
 * the addresses, because one conversation's `/report.csv` is not another's.
 */
export interface FileAccess {
  readonly textKey: readonly unknown[];
  readonly bytesKey: readonly unknown[];
  readText(): Promise<FileText>;
  readBytes(): Promise<Blob>;
  /**
   * Save it to disk.
   *
   * Per origin rather than derived from `readBytes`, because what a browser does
   * with a response is the server's decision: a workspace asks its route for
   * `download=true` to be answered `Content-Disposition: attachment`, which is also
   * the only way a type the API refuses to display inline comes back at all.
   */
  download(): Promise<void>;
}

/**
 * The file in a tab of its own.
 *
 * Generic across origins, which is what a blob buys: the bytes are already fetched
 * with the organization header this page is scoped to, so the tab shows the same
 * tenant's file. A bare URL would arrive without that header and be answered for the
 * caller's personal organization instead.
 *
 * Not revoked on a timer shorter than the tab's own life - a viewer that revokes the
 * URL it just opened shows the new tab an error. A minute is long enough for the
 * browser to have read it and short enough not to hold a PDF for the session.
 */
export async function openFileInNewTab(access: FileAccess): Promise<void> {
  const url = URL.createObjectURL(await access.readBytes());
  window.open(url, "_blank", "noopener,noreferrer");
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

/**
 * Hand a blob to the browser as a download, keeping the name it should have.
 *
 * The shared half of every origin's `download`: a blob URL, an anchor, a click, and
 * a revoke that has to happen *after* the click handler returns. Firefox and Safari
 * read the URL then, so revoking synchronously cancels the download there - Chrome
 * tolerates it, which is exactly how this ships broken for half the users.
 */
export function saveBlob(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
