"use client";

import type { AccountOwner, IntegrationProvider } from "@/hooks/use-connected-accounts";
import type { ConnectedAccount } from "@/types/mirage";
import { ImapSetupDialog } from "./imap-setup-dialog";
import { IntegrationSetupDialog } from "./integration-setup-dialog";
import { OdooSetupDialog } from "./odoo-setup-dialog";

export interface AccountSetupTarget {
  owner: AccountOwner;
  provider: IntegrationProvider;
  account?: ConnectedAccount;
}

/** Keep account repair on its original provider, owner and credential identity. */
export function ConnectedAccountSetup({
  target,
  onClose,
}: {
  target: AccountSetupTarget;
  onClose: () => void;
}) {
  const props = {
    owner: target.owner,
    reconnectAccount: target.account,
    onClose,
  };
  if (target.provider === "imap") return <ImapSetupDialog {...props} />;
  if (target.provider === "odoo") return <OdooSetupDialog {...props} />;
  return <IntegrationSetupDialog {...props} provider={target.provider} />;
}
