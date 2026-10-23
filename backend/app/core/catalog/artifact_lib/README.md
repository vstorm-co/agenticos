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
| `three-0.186.0/three.module.js`, `three.core.js`, `addons/controls/OrbitControls.js` | three.js as ES modules, in the package's own layout - the module imports its core by relative path | 0.186.0 | MIT | npm `three@0.186.0`, `build/` and `examples/jsm/controls/` |
| `mermaid-12.1.0.min.js` | Mermaid, the bundled build (`window.mermaid`) | 12.1.0 | MIT, with bundled dependencies below | npm `mermaid@12.1.0`, `dist/mermaid.min.js` |
| `idiomorph-0.8.0.min.js` | idiomorph, which morphs a visual's markup in place while it streams (`window.Idiomorph`) | 0.8.0 | 0BSD | npm `idiomorph@0.8.0`, `dist/idiomorph.min.js` |
| `leaflet-1.9.4/leaflet.js`, `leaflet.css` | Leaflet, the map library (`window.L`), which the map kit draws on | 1.9.4 | BSD-2-Clause | npm `leaflet@1.9.4`, `dist/` |
| `agenticos-1.css` | The console's design tokens for pages | 1 | Apache-2.0 (this repository) | written here |
| `agenticos-2.css` | The console's look and the `ao-` components pages are built from | 2 | Apache-2.0 (this repository) | written here |
| `agenticos-2.js` | `window.AO`: Chart.js in the console's style, number formatting, icons, tabs | 2 | Apache-2.0 (this repository) | written here |
| `agenticos-map-2.js` | `window.AOMap`: an itinerary of numbered pins on the deployment's tile server, or an outline without one | 2 | Apache-2.0 (this repository); the pin-drop timing adapted from Open Intelligent UI, MIT | written here |
| `agenticos-map-1.js` | Version 1, kept for the pages that name it; it drops the pins on load and keeps one height. `window.AOMap`: an itinerary of numbered pins on the deployment's tile server, or an outline without one | 1 | Apache-2.0 (this repository); the pin-drop timing adapted from Open Intelligent UI, MIT | written here |

The libraries are copied byte for byte from the registry tarballs, whose
`sha512` integrity was checked against the npm registry when they were added
(Chart.js, d3 and Lucide on 2026-09-30; three.js, Mermaid and idiomorph on
2026-10-16; Leaflet on 2026-10-21). `.pre-commit-config.yaml` excludes them from the whitespace hooks so
they stay that way. Chart.js, Lucide and Leaflet end with a `sourceMappingURL` comment for a
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

### three.js

The MIT License

Copyright © 2010-2026 three.js authors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.

### Mermaid

The MIT License (MIT)

Copyright (c) 2014 - 2022 Knut Sveidqvist

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

The Mermaid bundle includes its dependencies, each under its own licence:
DOMPurify 3 (MPL-2.0 OR Apache-2.0, used here under Apache-2.0; its header is kept
in the file), elkjs 0.9 (EPL-2.0 - distributed unmodified in object form; the
licence is at https://www.eclipse.org/legal/epl-2.0/ and the source at
https://github.com/kieler/elkjs), chevrotain (Apache-2.0), d3 (ISC), d3-sankey
(BSD-3-Clause), and under MIT: @braintree/sanitize-url, @iconify/utils,
@upsetjs/venn.js, cytoscape and its cose-bilkent and fcose layouts, dagre-d3-es,
dayjs, es-toolkit, katex, khroma, marked, roughjs, stylis, ts-dedent, uuid and
@mermaid-js/parser.

### idiomorph

Zero-Clause BSD
=============

Permission to use, copy, modify, and/or distribute this software for
any purpose with or without fee is hereby granted.

THE SOFTWARE IS PROVIDED “AS IS” AND THE AUTHOR DISCLAIMS ALL
WARRANTIES WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES
OF MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE
FOR ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY
DAMAGES WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN
AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT
OF OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

### Leaflet

BSD 2-Clause License

Copyright (c) 2010-2023, Volodymyr Agafonkin
Copyright (c) 2010-2011, CloudMade
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

### Open Intelligent UI

`agenticos-map-1.js` and `agenticos-map-2.js` adapt the pin-drop timing of
`createTripAnimator`, and the
`visual-design` skill borrows guidance from the playbook and skills, of Open
Intelligent UI (https://github.com/CopilotKit/OpenIntelligentUI, at
`8391a94c1c3939c679e40ddd7bfc08a9ef690e70`). The notice is kept in the file's
header.

The MIT License

Copyright (c) Atai Barkai

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
