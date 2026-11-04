# Custom brand icons

Drop an SVG here and it becomes servable at `GET /api/v1/catalog/icons/{name}`
and drawable in the console for any MCP catalog entry or model provider whose
icon name / id matches the filename.

The contract:

- **Filename is the id**: `acme.svg` draws for the catalog icon or provider id
  `acme`. Lowercase letters, digits and hyphens only (`^[a-z0-9][a-z0-9-]{0,63}$`);
  anything else is not served.
- **The file's colours are ignored.** The console renders every custom mark as
  a `currentColor` silhouette (CSS mask), so it stays monochrome and follows
  the theme no matter what the SVG contains. Ship a solid single-path mark -
  gradients and multi-colour art degrade into a blob.
- **Compiled-in marks win.** A name the bundled icon sets already carry
  (Simple Icons for MCP/connectors, lobehub for providers) is drawn from the
  bundle; the file here is the fallback for brands they do not know.

## Bundled sources

- `keenable.svg`: the official [Keenable documentation favicon](https://docs.keenable.ai/favicon.svg), adapted to a monochrome mask by retaining the original blue paths and transforms and removing the opaque white highlights from the transparent counters. The mark belongs to Keenable; the console renders it through the same theme-aware mask as other catalog icons.
- `otari.svg`: the official Otari mark from [mozilla-ai/otari](https://github.com/mozilla-ai/otari/blob/main/web/public/favicon.svg), rendered as a monochrome mask with the original transparent cutouts.
