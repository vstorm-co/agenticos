# text.extract

Reads the text of a TXT, JSON, CSV, text PDF or DOCX file. The format is the one
the file's bytes showed when it was stored, not its name. A PDF is read from its
text layer, page by page.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | `TextExtractInput` | `file` |
| `out` | output | `TextExtractOutput` | `text`, `source_format`, `page_count` |

## What it will not do

It does no OCR. A PDF page with no text and an image on it is a scan, and a scan
fails the step with `TEXT_EXTRACTION_NEEDS_OCR`, naming the pages, rather than
passing on a document that says nothing. A damaged document is
`DOCUMENT_CORRUPT`, a password-protected PDF `DOCUMENT_ENCRYPTED`, and another
format `UNSUPPORTED_FORMAT`. Text longer than `max_chars` is `TEXT_TOO_LONG`;
write a long one to a file with `convert.text_to_file`.
