/**
 * A CSV file as rows of cells: RFC 4180 quoting (a quoted cell may hold the
 * delimiter, a line break or a doubled quote), `\r\n` or `\n` line ends, and a
 * leading byte-order mark dropped.
 *
 * The delimiter is the one the first line holds more of, comma or semicolon: a
 * spreadsheet in a locale that writes decimals with a comma saves CSV with
 * semicolons. A last empty line - the one a file's final line break leaves - is
 * not a row.
 */
export function parseCsv(text: string): string[][] {
  const source = text.startsWith("﻿") ? text.slice(1) : text;
  const firstLine = source.slice(0, source.search(/\r?\n|$/));
  const delimiter = count(firstLine, ";") > count(firstLine, ",") ? ";" : ",";
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

function count(text: string, char: string): number {
  return text.split(char).length - 1;
}
