import { use } from "react";

import { AcceptInvitation } from "@/components/orgs/accept-invitation";

interface PageProps {
  params: Promise<{ token: string }>;
}

export default function AcceptInvitationPage({ params }: PageProps) {
  return <AcceptInvitation token={use(params).token} />;
}
