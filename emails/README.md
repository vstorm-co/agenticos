# Email templates

The 22 HTML/plain-text pairs in `compiled/` are the files the backend sends.
The backend image includes this directory; no template build runs when an email
is sent. `content.json` holds the copy and message types, and `build.py` holds
the shared email layout. Both outputs come from the same source so the text
alternative keeps the same facts and action links as the HTML.

## Editing and checking

From the repository root, using Python 3.12 or later:

```bash
python emails/build.py
python emails/build.py --check
cd backend
uv run pytest tests/test_email_templates.py -q
```

Edit `content.json` or the builder and commit the rebuilt pairs together. The
check refuses stale or orphaned compiled files. The backend tests also run it,
render every supplied template, and check placeholder, escaping and link
behavior. Billing templates remain available on disk; this design change does
not add billing events to `EmailKey` or change when any message is sent.

Runtime values retain the `[[variable]]` syntax. They are HTML-escaped by the
backend and stay unchanged in the plain-text body and subject. The first line
of every text file is `Subject: ...`. Workflow bodies and requested tools stay
plain text with their line breaks preserved. `asked_by` is already a complete
attribution sentence from the notification service; do not prepend another
"Requested by" label to it.

## Typography and delivery

Geist Sans Regular (400) is the body face; Medium (500) is used for headings,
actions and prominent figures. Geist Mono Regular is used for tool names.
The licensed WOFF2 files and their license are in
`frontend/public/fonts/email/`.

The renderer supplies `email_font_base_url` from
`FRONTEND_URL.rstrip('/') + '/fonts/email'`; callers do not need to pass it and
cannot override it. Production must set `FRONTEND_URL` to its public HTTPS
frontend URL, as it does for account links. Next.js serves those assets without
authentication and grants cross-origin reads only on that font path. Deploy the
backend templates and frontend assets together.

Web fonts are an enhancement. Clients that omit them use Arial/Helvetica for
text and Courier for tool names. Outlook's Word renderer gets explicit fallback
fonts and a 600px table wrapper. Layout, colors and links use inline styles;
small-screen rules stack detail rows, reduce padding, and widen the action.
Every action also has a visible, copyable URL. Messages contain no scripts,
image dependencies or tracking pixels.

The approved visual proof covers desktop and narrow layouts. Rendering tests
check the actual template data and HTML; they do not certify every inbox client.
No delivery or authentication behavior is changed by the design.

## Design sources

The approved email design adapts the neutral surfaces, blue action color,
spacing and typography conventions from
[t3UI](https://github.com/t3grp/t3UI/tree/e28bca7b48aec8cbcd3ebc6695edbfeb66ed9f08)
to table-based email markup. It does not import React components into email.

The design review applied and adapted
[Unslop](https://github.com/heydamir/unslop/tree/a6f121eee5f29c2f74976b75456feae8b66afb3a)
by Damir Sokolovsky, licensed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/): direct event headings,
purpose-specific detail sections, restrained colors, and no decorative badges
or generic slogans.

[Geist](https://github.com/vercel/geist-font/tree/ef2597cfc42f4797676df105517ccc0a1cfa6569)
is by Vercel and the Geist Project Authors, under the SIL Open Font License 1.1.
The original font files and license are retained beside the assets.
