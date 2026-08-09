/**
 * Reading a comma- or tab-separated file into rows.
 *
 * There is a parser here rather than a `split(",")` for one reason, and it is the
 * common case: a quoted field holding a comma. Everything else it handles - an
 * escaped quote, a newline inside a field, Windows line endings - is the same
 * mechanism seen from a different angle, which is why they are one function.
 *
 * RFC 4180-ish, and deliberately not a library: what this is for is showing somebody
 * a table of what their agent wrote, and it is bounded at five hundred rows before it
 * reaches the DOM.
 */
export function parseDelimited(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let inQuotes = false;
  let index = 0;

  while (index < text.length) {
    const char = text[index];
    if (inQuotes) {
      if (char === '"') {
        // A doubled quote inside a quoted field is one quote, which is the only
        // escape the format has.
        if (text[index + 1] === '"') {
          field += '"';
          index += 2;
          continue;
        }
        inQuotes = false;
        index++;
        continue;
      }
      field += char;
      index++;
      continue;
    }
    if (char === '"') {
      inQuotes = true;
      index++;
      continue;
    }
    if (char === "," || char === "\t") {
      row.push(field);
      field = "";
      index++;
      continue;
    }
    if (char === "\n" || char === "\r") {
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
      if (char === "\r" && text[index + 1] === "\n") index += 2;
      else index++;
      continue;
    }
    field += char;
    index++;
  }
  // A file that does not end in a newline still ends in a row.
  if (field.length > 0 || row.length > 0) {
    row.push(field);
    rows.push(row);
  }
  return rows;
}
