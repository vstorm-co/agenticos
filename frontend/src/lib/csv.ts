/**
 * A CSV file as rows of cells: RFC 4180 quoting (a quoted cell may hold the
 * delimiter, a line break or a doubled quote), `\r\n` or `\n` line ends, and a
 * leading byte-order mark dropped.
 *
 * The delimiter is the comma or semicolon that occurs more often, unquoted, in the
 * first record: a spreadsheet in a locale that writes decimals with a comma saves
 * CSV with semicolons. A tie keeps the comma.
 * A last empty line - the one a file's final line break leaves - is not a row.
 */
export function parseCsv(text: string): string[][] {
  const source = text.startsWith("﻿") ? text.slice(1) : text;
  return readRows(source, chooseDelimiter(source));
}

/**
 * Counts the unquoted commas and semicolons in the first record. A quote opens
 * a quoted cell only at a cell start, so quoted text is not counted.
 */
function chooseDelimiter(source: string): string {
  let commas = 0;
  let semicolons = 0;
  let quoted = false;
  let atCellStart = true;

  for (let i = 0; i < source.length; i++) {
    const char = source[i];
    if (quoted) {
      if (char === '"' && source[i + 1] === '"') {
        i++;
      } else if (char === '"') {
        quoted = false;
      }
    } else if (char === "\r" || char === "\n") {
      break;
    } else if (char === '"' && atCellStart) {
      quoted = true;
      atCellStart = false;
    } else if (char === "," || char === ";") {
      if (char === ",") {
        commas++;
      } else {
        semicolons++;
      }
      atCellStart = true;
    } else {
      atCellStart = false;
    }
  }
  return semicolons > commas ? ";" : ",";
}

/** Splits the text into rows; a quoted cell may hold the delimiter or a line break. */
function readRows(source: string, delimiter: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;

  for (let i = 0; i < source.length; i++) {
    const char = source[i];
    if (quoted) {
      if (char === '"' && source[i + 1] === '"') {
        cell += '"';
        i++;
      } else if (char === '"') {
        quoted = false;
      } else {
        cell += char;
      }
    } else if (char === '"' && cell === "") {
      quoted = true;
    } else if (char === delimiter) {
      row.push(cell);
      cell = "";
    } else if (char === "\n" || char === "\r") {
      if (char === "\r" && source[i + 1] === "\n") i++;
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
    } else {
      cell += char;
    }
  }
  if (cell !== "" || row.length > 0) {
    row.push(cell);
    rows.push(row);
  }
  return rows;
}
