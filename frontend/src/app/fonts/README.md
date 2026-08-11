# Vendored web fonts

`next/font/local` reads these; nothing here is fetched at build time. That is the whole
point — `next/font/google` resolved the same families against `fonts.gstatic.com` while
`next build` ran, so a 404 from the CDN failed the build on branches that had not touched
the frontend at all (#572). A vendored file cannot 404.

Each file is the **latin** subset of the family's variable font, range-limited to the
weights `layout.tsx` asks for. Weights outside the declared range are synthesized by the
browser, so widening a range means re-fetching, not editing the declaration.

| File | Family | Weights | Google Fonts version |
| --- | --- | --- | --- |
| `bricolage-grotesque-latin-700-800.woff2` | Bricolage Grotesque | 700–800 | v9 |
| `inter-latin-400-700.woff2` | Inter | 400–700 | v20 |
| `geist-mono-latin-400-500.woff2` | Geist Mono | 400–500 | v6 |

All three are SIL Open Font License 1.1 — see `OFL.txt`, which carries the copyright
notice of each.

## Refreshing one

Ask the CSS API for the family and weight range with a browser user agent (it serves
`.ttf` to anything it does not recognise), take the URL from the `/* latin */` block, and
download it under the same name:

```bash
UA='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'
curl -sS -A "$UA" 'https://fonts.googleapis.com/css2?family=Inter:wght@400..700&display=swap'
curl -sS -o inter-latin-400-700.woff2 '<the url from the latin block>'
```

The version in the table is the `/v20/` path segment of that URL. Bump it here when it
moves, so a stale file is visible rather than assumed current.
