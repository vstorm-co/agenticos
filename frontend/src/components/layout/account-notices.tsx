import { ReceivedInvitations } from "@/components/orgs/received-invitations";
import styles from "./account-notices.module.css";

/** Invitations float outside page content; setup remains in the sidebar. */
export function AccountNotices() {
  return (
    <div data-account-notices className={styles.stack}>
      <ReceivedInvitations />
    </div>
  );
}
