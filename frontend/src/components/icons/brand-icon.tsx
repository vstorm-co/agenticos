import type { SVGProps } from "react";
import type { IconType } from "react-icons";
import { FaAws, FaLinkedin, FaMicrosoft, FaSlack } from "react-icons/fa6";
import {
  SiAirtable,
  SiAsana,
  SiAtlassian,
  SiBox,
  SiCalendly,
  SiClickup,
  SiCloudflare,
  SiDatabricks,
  SiDeepl,
  SiElastic,
  SiElevenlabs,
  SiExcalidraw,
  SiGitbook,
  SiGitlab,
  SiGooglebigquery,
  SiGrafana,
  SiHubspot,
  SiHuggingface,
  SiLucid,
  SiMailchimp,
  SiMake,
  SiMiro,
  SiMixpanel,
  SiN8N,
  SiNetlify,
  SiPagerduty,
  SiPaypal,
  SiPosthog,
  SiPostman,
  SiRailway,
  SiReplit,
  SiResend,
  SiSemrush,
  SiShopify,
  SiSimilarweb,
  SiSnowflake,
  SiSupabase,
  SiSurveymonkey,
  SiTodoist,
  SiTrello,
  SiTypeform,
  SiWebflow,
  SiWix,
  SiWordpress,
  SiXero,
  SiZapier,
  SiZoom,
  SiDropbox,
  SiFigma,
  SiGithub,
  SiGmail,
  SiGoogle,
  SiGoogledrive,
  SiIntercom,
  SiLinear,
  SiLoom,
  SiModelcontextprotocol,
  SiNotion,
  SiPostgresql,
  SiSentry,
  SiStripe,
  SiVercel,
} from "react-icons/si";

/** Brand glyphs sourced from a maintained icon set (Simple Icons via
 *  react-icons, Font Awesome for Microsoft and LinkedIn, which Simple Icons
 *  no longer ships) - never hand-authored SVG paths,
 *  so the marks stay correct and recognizable. Monochrome (currentColor) so
 *  they inherit the surrounding text color. */

export type BrandName =
  | "gdrive"
  | "slack"
  | "notion"
  | "github"
  | "dropbox"
  | "gmail"
  | "google"
  | "microsoft"
  | "stripe"
  | "linear"
  | "linkedin"
  | "vercel"
  | "figma"
  | "loom"
  | "intercom"
  | "s3"
  | "aws"
  | "sentry"
  | "postgres"
  | "asana"
  | "airtable"
  | "zapier"
  | "make"
  | "n8n"
  | "clickup"
  | "trello"
  | "todoist"
  | "calendly"
  | "zoom"
  | "miro"
  | "lucid"
  | "excalidraw"
  | "box"
  | "shopify"
  | "mailchimp"
  | "resend"
  | "posthog"
  | "mixpanel"
  | "snowflake"
  | "databricks"
  | "bigquery"
  | "pagerduty"
  | "postman"
  | "netlify"
  | "railway"
  | "replit"
  | "huggingface"
  | "gitbook"
  | "webflow"
  | "wix"
  | "wordpress"
  | "semrush"
  | "similarweb"
  | "typeform"
  | "surveymonkey"
  | "deepl"
  | "elevenlabs"
  | "xero"
  | "hubspot"
  | "paypal"
  | "atlassian"
  | "gitlab"
  | "supabase"
  | "grafana"
  | "elastic"
  | "cloudflare"
  /** The Model Context Protocol mark, for a server that is only "an MCP server". */
  | "mcp";

const ICONS: Record<BrandName, IconType> = {
  gdrive: SiGoogledrive,
  slack: FaSlack,
  notion: SiNotion,
  github: SiGithub,
  dropbox: SiDropbox,
  gmail: SiGmail,
  google: SiGoogle,
  microsoft: FaMicrosoft,
  stripe: SiStripe,
  linear: SiLinear,
  linkedin: FaLinkedin,
  vercel: SiVercel,
  figma: SiFigma,
  loom: SiLoom,
  intercom: SiIntercom,
  s3: FaAws,
  aws: FaAws,
  sentry: SiSentry,
  postgres: SiPostgresql,
  asana: SiAsana,
  airtable: SiAirtable,
  zapier: SiZapier,
  make: SiMake,
  n8n: SiN8N,
  clickup: SiClickup,
  trello: SiTrello,
  todoist: SiTodoist,
  calendly: SiCalendly,
  zoom: SiZoom,
  miro: SiMiro,
  lucid: SiLucid,
  excalidraw: SiExcalidraw,
  box: SiBox,
  shopify: SiShopify,
  mailchimp: SiMailchimp,
  resend: SiResend,
  posthog: SiPosthog,
  mixpanel: SiMixpanel,
  snowflake: SiSnowflake,
  databricks: SiDatabricks,
  bigquery: SiGooglebigquery,
  pagerduty: SiPagerduty,
  postman: SiPostman,
  netlify: SiNetlify,
  railway: SiRailway,
  replit: SiReplit,
  huggingface: SiHuggingface,
  gitbook: SiGitbook,
  webflow: SiWebflow,
  wix: SiWix,
  wordpress: SiWordpress,
  semrush: SiSemrush,
  similarweb: SiSimilarweb,
  typeform: SiTypeform,
  surveymonkey: SiSurveymonkey,
  deepl: SiDeepl,
  elevenlabs: SiElevenlabs,
  xero: SiXero,
  hubspot: SiHubspot,
  paypal: SiPaypal,
  atlassian: SiAtlassian,
  gitlab: SiGitlab,
  supabase: SiSupabase,
  grafana: SiGrafana,
  elastic: SiElastic,
  cloudflare: SiCloudflare,
  mcp: SiModelcontextprotocol,
};

interface BrandIconProps extends SVGProps<SVGSVGElement> {
  name: BrandName;
}

export function BrandIcon({ name, "aria-label": ariaLabel, ...props }: BrandIconProps) {
  const Icon = ICONS[name];
  // Decorative by default - paired with a text label in our layouts. Pass
  // `aria-label` explicitly to make it semantic (e.g. icon-only buttons).
  const a11y = ariaLabel ? { role: "img", "aria-label": ariaLabel } : { "aria-hidden": true };
  return <Icon {...a11y} {...props} />;
}

/**
 * Connector types, as the backend spells them, to the mark that shows one.
 *
 * More than one spelling reaches the same product: the registry key is
 * `gdrive`, older rows carry `google_drive`, and `aws` and `s3` are the same
 * bucket. Kept in one place because every surface that lists a sync source
 * needs the mapping, and three copies of it is how one of them ends up showing
 * a generic database icon for Drive.
 */
const CONNECTOR_BRANDS: Record<string, BrandName> = {
  google_drive: "gdrive",
  gdrive: "gdrive",
  drive: "gdrive",
  github: "github",
  notion: "notion",
  slack: "slack",
  dropbox: "dropbox",
  s3: "s3",
  aws: "s3",
};

/** The brand mark for a connector type, or `undefined` when it has none. */
export function connectorBrand(connectorType: string): BrandName | undefined {
  return CONNECTOR_BRANDS[connectorType];
}

/** Whether a catalog's icon name is one this set actually draws. */
export function isBrandName(value: string): value is BrandName {
  return value in ICONS;
}
