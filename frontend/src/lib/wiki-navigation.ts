import type { WikiPage } from "./wiki-graph";
import { wikiGroup, type WikiGrouping } from "./wiki-flow";

export function inWikiFolder(path: string, folder: string | null): boolean {
  return (
    folder === null || path.replace(/^\/+/, "").startsWith(folder.replace(/^\/+|\/+$/g, "") + "/")
  );
}

export function filterWikiPages(
  pages: readonly WikiPage[],
  search: string,
  folder: string | null,
  hidden: ReadonlySet<string>,
  grouping: WikiGrouping,
): WikiPage[] {
  const query = search.trim().toLocaleLowerCase().replace(/^#/, "");
  return pages.filter(
    (page) =>
      inWikiFolder(page.path, folder) &&
      !hidden.has(wikiGroup(page, grouping)) &&
      [page.title, page.path, ...page.tags, ...page.aliases].some((value) =>
        value.toLocaleLowerCase().includes(query),
      ),
  );
}
