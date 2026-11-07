# Personal desktop OAuth: release decision

Decision date: 2026-11-07. Scope: #2797, personal accounts on arbitrary
self-hosted deployments. Organization accounts keep the deployment's own app.

**No-go for a shared published desktop app in this release, for all three
providers.** Public-client OAuth is technically possible. Publishing and operating
one app is a separate service commitment; changing the redirect alone does not
complete it. This is a release decision, not a claim that desktop OAuth is
technically prohibited. No desktop token-transfer endpoint or prototype ships in
this PR. Revisit with an owner, published app registrations and a funded review.

## Slack

PKCE supports custom schemes and loopback redirects. Desktop redirects can request
user scopes, including the Web API scopes this integration uses, but cannot request
bot scopes. Enabling PKCE is a one-way change requiring Slack support to reverse.
Custom-scheme redirects always get rotating tokens; PKCE refresh tokens expire
after 30 days. A deployment must therefore handle rotation and eventual reconnect,
not assume a permanent refresh token.

The remaining release blocker is distribution: a shared Vstorm app must meet Slack
Marketplace/distribution requirements and each workspace's approval policy. PKCE
by itself is not evidence that an app is approved for Slack MCP. This integration
uses the Web API, so MCP eligibility is not a prerequisite for its tools. No
verification fee or approval deadline has been established; engineering/support
and review effort must be budgeted separately. Use the deployment's internal app
or an existing token until that work is commissioned.

Sources: [Slack PKCE](https://docs.slack.dev/authentication/using-pkce/),
[Marketplace](https://docs.slack.dev/slack-marketplace/).

## Google

Installed desktop clients support PKCE and loopback redirects. That is compatible
with the desired direct device-to-deployment flow. It does not remove verification
for sensitive/restricted scopes. Gmail read access is restricted; Google requires
restricted-scope verification unless an exception applies. Restricted data accessed
from or through a third-party server can require an annual assessment by a
Google-approved assessor. A public app whose tokens are transferred to arbitrary
self-hosted servers needs that deployment model explicitly reviewed; we cannot
assume a local-only exception.

No assessor quote is available, so this decision does not invent a CASA price.
The cost includes verification work, any required recurring assessment, privacy
policy/support ownership and maintaining the app. A future narrower public app
could request non-mail scopes first, but would not satisfy this issue's Gmail
experience. Keep deployment-specific clients and Workspace delegation for now.

Sources: [desktop OAuth](https://developers.google.com/identity/protocols/oauth2/native-app),
[restricted-scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification).

## Microsoft

A public desktop client can use a system browser and a loopback redirect without a
confidential client secret. A multi-tenant registration can support the intended
organizational sign-in audience, with personal accounts only for products that
support them. Delegated Graph permissions remain subject to tenant consent policy;
public-client PKCE does not eliminate admin consent. Excel delegated APIs and
Teams work/school restrictions remain unchanged.

No protocol blocker was found. The release is nevertheless no-go for one published
Vstorm client until registration, verified publisher ownership, consent policy,
support and token handoff/revocation are reviewed as a product. No separate
verification fee has been established; budget engineering and tenant acceptance
testing rather than assuming universal one-click access. The per-deployment Entra
wizard already provides the direct Graph path required by #2797.

Sources: [desktop client configuration](https://learn.microsoft.com/en-us/entra/identity-platform/scenario-desktop-app-configuration),
[application consent](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/user-admin-consent-overview).

## Security conditions for a follow-up

The desktop must bind the authorization state and PKCE verifier to the exact local
attempt and authenticated device link. Bind a loopback listener to loopback only;
open the system browser. The user must confirm which deployment receives the grant.
Transmit tokens only over that deployment's authenticated, encrypted device link,
never a Vstorm relay. Seal refresh credentials with the existing Vault envelope,
include provider/client/subject identity in source review, serialize refresh-token
rotation, and revoke/delete from the console. Reauthorizing a source invalidates
unattended approvals. Do not put public-client secrets into the desktop bundle.

A future go decision needs an end-to-end personal Slack or Google prototype with
a localhost deployment, plus negative tests for state mismatch, device/deployment
substitution, rotation races and revoked links. It is deliberately a follow-up,
not an unverified promise in this release.
