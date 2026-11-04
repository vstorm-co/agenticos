# html.parse

Reads HTML into its text, its links and what a CSS selector picks. It exists for
the HTML a flow meets: a mail body, a page an `http.request` or `http.download`
step brought back. `text.extract` reads documents (TXT, JSON, CSV, PDF, DOCX), not
markup - HTML is stored as plain text, so it would hand the tags back as the text.

Nothing is fetched and nothing runs: no image, stylesheet, base address or link is
requested, scripts are only text, and the parser is the standard library's, so no
XML entity is expanded. Every field is bounded.

The parse runs in a child process (`_child.py`) in its own session, with 20 seconds
of wall-clock time, a CPU limit and 2 GiB of address space, because a descendant
selector such as `p div div` over deeply nested markup can take minutes and a
thread cannot be stopped. When the deadline passes the child's process group is
killed and the step fails with `HTML_TOO_COMPLEX`; cancelling the step kills it too.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | `HtmlParseInput` | `html` (at most 2,000,000 characters) or `file` (at most 5,000,000 bytes) - exactly one |
| `out` | output | `HtmlParseOutput` | `title`, `text`, `text_truncated`, `links`, `links_truncated`, `matches`, `match_count` |

## What it will not do

It does not follow a link, load a page or run a script. It drops `javascript:`,
`vbscript:` and `data:` links so a later step never receives one. It does not check
a file's declared type: any file the run may read is decoded, lossily if need be,
and parsed - a PDF is read as garbled text, not refused. A step with no settings or
no input is `HTML_PARSE_NOT_CONFIGURED`, a page that takes over 20 seconds is
`HTML_TOO_COMPLEX`, bytes no decoder can read at all, or a reader process that dies,
are `HTML_NOT_READABLE` (its `reason` detail says which), and a missing or oversized
file is `FILE_NOT_FOUND` or `FILE_TOO_LARGE`. The work per anchor and per match is bounded, so a page built to
be slow is cut short, not waited for.
