/**
 * A table from an answer, copied in the two forms its destination might want.
 *
 * `text/html` is what a spreadsheet, a document or Notion reads when it pastes a
 * real table; `text/plain` is what a chat box, an editor or a terminal gets, and
 * a markdown table is what those read back as one. Copying one form only meant
 * either a pasted table of pipes in a spreadsheet or a pasted grid of cells in a
 * markdown file.
 */

/** A rendered table as rows of cell text, the header rows first. */
export interface TableText {
  head: string[][];
  body: string[][];
}

/** The text of every cell, whitespace collapsed the way it was drawn. */
export function readTable(table: HTMLTableElement): TableText {
  const rows = (section: HTMLTableSectionElement) =>
    Array.from(section.rows, (row) =>
      Array.from(row.cells, (cell) => String(cell.textContent).replace(/\s+/g, " ").trim()),
    );
  return {
    head: table.tHead === null ? [] : rows(table.tHead),
    body: Array.from(table.tBodies).flatMap(rows),
  };
}

/**
 * A GFM table, as wide as its widest row.
 *
 * A pipe inside a cell is escaped, or it would end the cell it is in. A table
 * with no header row still gets one, empty, because GFM has no table without it.
 */
export function tableToMarkdown({ head, body }: TableText): string {
  const width = Math.max(1, ...[...head, ...body].map((row) => row.length));
  const line = (cells: string[]) =>
    `| ${Array.from({ length: width }, (_, i) => (cells[i] ?? "").replaceAll("|", "\\|")).join(" | ")} |`;
  return [
    line(head[0] ?? []),
    line(Array.from({ length: width }, () => "---")),
    ...head.slice(1).map(line),
    ...body.map(line),
  ].join("\n");
}

/** A bare HTML table - no classes, no styles - for a destination to style its own way. */
export function tableToHtml({ head, body }: TableText): string {
  const row = (cells: string[], tag: "th" | "td") =>
    `<tr>${cells.map((cell) => `<${tag}>${escapeHtml(cell)}</${tag}>`).join("")}</tr>`;
  const thead = head.map((cells) => row(cells, "th")).join("");
  const tbody = body.map((cells) => row(cells, "td")).join("");
  return `<table><thead>${thead}</thead><tbody>${tbody}</tbody></table>`;
}

function escapeHtml(text: string): string {
  return text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}
