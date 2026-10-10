import type { ApiKeyScopeCatalog } from "./api-keys";
import type { Permission } from "./permissions";

/** What an MCP client is asking for, as the consent page shows it. */
export interface OAuthConsentRequest {
  request_id: string;
  client_name: string;
  client_uri: string | null;
  /** Where the browser goes back to, as a host - the thing worth checking. */
  redirect_host: string;
  organization_id: string;
  organization_name: string;
  catalog: ApiKeyScopeCatalog;
}

export interface OAuthConsentAnswer {
  redirect_to: string;
}

/** An application somebody connected, acting as them in this organization. */
export interface ConnectedApp {
  id: string;
  client_name: string;
  client_uri: string | null;
  user_id: string;
  user_email: string;
  scopes: Permission[];
  created_at: string;
}

export interface ConnectedAppList {
  items: ConnectedApp[];
  total: number;
}
