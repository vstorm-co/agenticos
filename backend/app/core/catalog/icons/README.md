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
