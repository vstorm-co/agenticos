# The library set served to artifacts

A published page has no network (`docs/artifacts.md#how-the-page-is-isolated`), so
it cannot load a chart library from a CDN. These files are the exception: the
deployment serves them itself, from the artifact content origin under
`/api/v1/artifact-lib/<file>`, and the page's policy allows scripts and styles from
that path and from nowhere else. Nothing leaves the deployment, so an air-gapped one
works the same way.

`app/services/artifact.py` lists what is served (`ARTIFACT_LIBRARY`). A file here
that is not listed there is not served.

| File | What | Version | Licence | Source |
|---|---|---|---|---|
| `chart-4.5.1.umd.min.js` | Chart.js, the UMD build (`window.Chart`) | 4.5.1 | MIT | npm `chart.js@4.5.1`, `dist/chart.umd.min.js` |
| `d3-7.9.0.min.js` | d3, the bundled build (`window.d3`) | 7.9.0 | ISC | npm `d3@7.9.0`, `dist/d3.min.js` |
| `lucide-1.46.0.min.js` | Lucide icons, the UMD build (`window.lucide`) | 1.46.0 | ISC, MIT for the icons from Feather | npm `lucide@1.46.0`, `dist/umd/lucide.min.js` |
| `agenticos-1.css` | The console's design tokens for pages | 1 | Apache-2.0 (this repository) | written here |
| `agenticos-2.css` | The console's look and the `ao-` components pages are built from | 2 | Apache-2.0 (this repository) | written here |
| `agenticos-2.js` | `window.AO`: Chart.js in the console's style, number formatting, icons, tabs | 2 | Apache-2.0 (this repository) | written here |

The three libraries are copied byte for byte from the registry tarballs, whose
`sha512` integrity was checked against the npm registry when they were added
(2026-09-30). `.pre-commit-config.yaml` excludes them from the whitespace hooks so
they stay that way. Chart.js and Lucide end with a `sourceMappingURL` comment for a
map that is not shipped; a browser asks for it only with developer tools open.

Lucide is the version the console draws its own icons from (`lucide-react`), so an
icon on a page is the icon of the same name in the product.

## Changing the set

Every name carries its version and is cached for a year (`immutable`). Upgrading a
library adds a new file beside the old one and a new entry in `ARTIFACT_LIBRARY`,
rather than replacing it: a page published last month names the old file and must
keep rendering. Remove an old file only when no kept version can still name it.

Add the licence to `licenses/components.toml` and `NOTICE`, and the file to the
`artifact-pages` bundled skill, which is how an agent learns the set exists.

## Licences

### Chart.js

The MIT License (MIT)

Copyright (c) 2014-2024 Chart.js Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy of this
software and associated documentation files (the "Software"), to deal in the Software
without restriction, including without limitation the rights to use, copy, modify,
merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
permit persons to whom the Software is furnished to do so, subject to the following
conditions:

The above copyright notice and this permission notice shall be included in all copies
or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF
CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE
OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

### d3

Copyright 2010-2023 Mike Bostock

Permission to use, copy, modify, and/or distribute this software for any purpose
with or without fee is hereby granted, provided that the above copyright notice
and this permission notice appear in all copies.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH
REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY AND
FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT,
INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM LOSS
OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER
TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR PERFORMANCE OF
THIS SOFTWARE.

### Lucide

ISC License

Copyright (c) 2026 Lucide Icons and Contributors

Permission to use, copy, modify, and/or distribute this software for any
purpose with or without fee is hereby granted, provided that the above
copyright notice and this permission notice appear in all copies.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

The icons Lucide derives from the Feather project are under the MIT License:

Copyright (c) 2013-present Cole Bemis

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
