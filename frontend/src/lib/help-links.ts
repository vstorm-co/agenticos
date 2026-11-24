/**
 * Where "Help" in the sidebar points.
 *
 * The docs site is the published MkDocs site: `site_url` in `mkdocs.yml`
 * and the "Documentation" link in the README. The Learn track is its
 * `/learn/` landing (`docs/learn/index.md`). Bug reports follow the flow
 * `docs/help.md` names - this repository's issue templates - with the running
 * console version filled into the template's Version field, which takes a
 * release tag or a commit.
 *
 * No commit hash is available at runtime: nothing in the console surfaces
 * one, so the release tag is what a report carries. A deployment built from
 * a commit past a release still names the release it is based on.
 */

export const DOCS_URL = "https://vstorm-co.github.io/agenticos/";

export const LEARN_URL = `${DOCS_URL}learn/`;

const ISSUE_NEW_URL = "https://github.com/t3grp/agenticos/issues/new";

/** The bug-report form, with the running console version filled in. */
export function reportProblemUrl(version: string): string {
  const params = new URLSearchParams({
    template: "bug_report.yml",
    version: `v${version}`,
  });
  return `${ISSUE_NEW_URL}?${params.toString()}`;
}
