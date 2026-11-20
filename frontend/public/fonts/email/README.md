# Email web fonts

These are Geist Sans and Geist Mono static web fonts distributed under the SIL Open Font License 1.1. They are copied from the official `vercel/geist-font` repository at commit `ef2597cfc42f4797676df105517ccc0a1cfa6569`:

- `Geist-Regular.woff2` — `fonts/Geist/webfonts/Geist-Regular.woff2` (Git blob `3eb6a71182069bf820a3cb1909cdee101be97dac`)
- `Geist-Medium.woff2` — `fonts/Geist/webfonts/Geist-Medium.woff2` (Git blob `76d44dafad237c31d4b3e14be8b3b1f7a25a3722`)
- `GeistMono-Regular.woff2` — `fonts/GeistMono/webfonts/GeistMono-Regular.woff2` (Git blob `d9d3833a0a0c6d91f4c17d05cfe4549cc6d80115`)
- `OFL.txt` — repository root `OFL.txt` (source Git blob `999fa2373263f4ce66077075c9ede594c6a49510`; trailing whitespace normalized)

Next.js serves these public files at `/fonts/email/Geist-Regular.woff2`, `/fonts/email/Geist-Medium.woff2`, and `/fonts/email/GeistMono-Regular.woff2`. Email templates must use an absolute runtime URL based on the deployment's configured frontend origin because email clients cannot resolve root-relative URLs. Keep system-font fallbacks: many email clients do not load web fonts.
