import type { LucideIcon } from "lucide-react";

import type { BrandName } from "@/lib/brand-glyphs.generated";
import { navSectionFor } from "@/lib/nav-sections";

/**
 * The service a web address belongs to, by the domains people actually link.
 *
 * Keyed on the registrable domain rather than on the MCP server's host: an
 * agent's Notion tool lives at `mcp.notion.com`, and the page it links to is on
 * `notion.so`. A suffix match, so `acme.atlassian.net` and `docs.github.com`
 * find their service and `notgithub.com` does not.
 */
const BRAND_DOMAINS: ReadonlyArray<readonly [string, BrandName]> = [
  ["notion.so", "notion"],
  ["notion.site", "notion"],
  ["notion.com", "notion"],
  ["github.com", "github"],
  ["gitlab.com", "gitlab"],
  ["linear.app", "linear"],
  ["atlassian.net", "atlassian"],
  ["atlassian.com", "atlassian"],
  ["slack.com", "slack"],
  ["figma.com", "figma"],
  ["hubspot.com", "hubspot"],
  ["stripe.com", "stripe"],
  ["airtable.com", "airtable"],
  ["asana.com", "asana"],
  ["trello.com", "trello"],
  ["miro.com", "miro"],
  ["canva.com", "canva"],
  ["dropbox.com", "dropbox"],
  ["box.com", "box"],
  ["mail.google.com", "gmail"],
  ["docs.google.com", "gdrive"],
  ["drive.google.com", "gdrive"],
  ["clickup.com", "clickup"],
  ["calendly.com", "calendly"],
  ["cal.com", "caldotcom"],
  ["loom.com", "loom"],
  ["sentry.io", "sentry"],
  ["datadoghq.com", "datadog"],
  ["grafana.com", "grafana"],
  ["grafana.net", "grafana"],
  ["intercom.com", "intercom"],
  ["mailchimp.com", "mailchimp"],
  ["posthog.com", "posthog"],
  ["mixpanel.com", "mixpanel"],
  ["pagerduty.com", "pagerduty"],
  ["paypal.com", "paypal"],
  ["shopify.com", "shopify"],
  ["myshopify.com", "shopify"],
  ["supabase.com", "supabase"],
  ["supabase.co", "supabase"],
  ["vercel.com", "vercel"],
  ["vercel.app", "vercel"],
  ["netlify.com", "netlify"],
  ["netlify.app", "netlify"],
  ["zoom.us", "zoom"],
  ["typeform.com", "typeform"],
  ["webflow.com", "webflow"],
  ["wordpress.com", "wordpress"],
  ["xero.com", "xero"],
  ["zapier.com", "zapier"],
  ["todoist.com", "todoist"],
  ["huggingface.co", "huggingface"],
  ["sharepoint.com", "microsoft"],
  ["office.com", "microsoft"],
  ["microsoft.com", "microsoft"],
];

/** The host of an address, without a leading `www.`, or null for one that is not a URL. */
export function hostOf(url: string): string | null {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return null;
  }
}

/** The service an address belongs to, or null for a site with no mark of its own. */
export function brandForUrl(url: string): BrandName | null {
  const host = hostOf(url);
  if (host === null) return null;
  const found = BRAND_DOMAINS.find(([domain]) => host === domain || host.endsWith(`.${domain}`));
  return found ? found[1] : null;
}

const APP_PATH = /^\/apps\/[0-9a-f-]{36}\/?$/i;

/**
 * Whether an address is one of this console's own apps - the link an agent
 * writes after publishing one, absolute, with the organization in its query.
 */
export function isAppLink(href: string, origin: string): boolean {
  try {
    const url = new URL(href, origin);
    return url.origin === origin && APP_PATH.test(url.pathname);
  } catch {
    return false;
  }
}

/**
 * The icon of the console section a relative link opens - `/routines`, `/mcp-servers`
 * - as the sidebar draws it, so a link an agent writes to a page wears that
 * page's mark. `null` for anything else: another site, a fragment, a page
 * outside every section.
 */
export function consolePageIcon(href: string, origin: string): LucideIcon | null {
  if (!href.startsWith("/") || href.startsWith("//")) return null;
  return navSectionFor(new URL(href, origin).pathname)?.item.icon ?? null;
}
