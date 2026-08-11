# Vendored web fonts

`next/font/local` reads these; nothing here is fetched at build time. That is the whole
point — `next/font/google` resolved the same families against `fonts.gstatic.com` while
`next build` ran, so a 404 from the CDN failed the build on branches that had not touched
the frontend at all (#572). A vendored file cannot 404.

Each file is the **latin** subset of the family's variable font and carries that family's
full `wght` axis: Google does not axis-subset, so `wght@400..700` and `wght@100..900`
return the same bytes. The range in `layout.tsx` is a declaration about which weights the
face may serve, not a property of the file — a weight outside it is clamped, not
synthesized. Widening one is a one-line edit to `layout.tsx`, with nothing to re-download.

So the Weights column below is what we declare; the axis column is what the file actually
holds.

| File | Family | Declared | Axis in the file | Google Fonts version |
| --- | --- | --- | --- | --- |
| `bricolage-grotesque-latin.woff2` | Bricolage Grotesque | 700–800 | 200–800 | v9 |
| `inter-latin.woff2` | Inter | 400–700 | 100–900 | v20 |
| `geist-mono-latin.woff2` | Geist Mono | 400–500 | 100–900 | v6 |

All three are SIL Open Font License 1.1 — see `OFL.txt`, which carries the copyright
notice of each.

## Refreshing one

Ask the CSS API for the family with a browser user agent (it serves `.ttf` to anything it
does not recognise), take the URL from the `/* latin */` block, and download it under the
same name. Ask for the family's full axis — any range returns that same file, and asking
for the full one keeps the request honest about what arrives:

```bash
UA='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'
curl -sS -A "$UA" 'https://fonts.googleapis.com/css2?family=Inter:wght@100..900&display=swap'
curl -sS -o inter-latin.woff2 '<the url from the latin block>'
```

The version in the table is the `/v20/` path segment of that URL. Bump it here when it
moves, so a stale file is visible rather than assumed current.
