# Directory sign-in and groups

A company that runs Active Directory, OpenLDAP or FreeIPA already knows who
works there and which teams they belong to. This page covers the three ways
AgenticOS can use that knowledge. People can sign in with their directory
account. A domain-joined browser can sign them in with its Kerberos ticket. And
directory groups can decide which organizations people join, with which role,
and which groups they are in.

Three pieces make that up, and they work independently:

| Piece | What it does | Configured by |
|---|---|---|
| [Groups](#groups) | Named sets of an organization's members that a resource can be shared with | Members with `members:manage`, in the console |
| [Directory group mappings](#directory-group-mappings) | "Everyone in this directory group joins as this role, in this group" | Members with `members:manage` and `roles:manage` |
| [Directory sign-in](#signing-in-with-a-directory-account) | LDAP password sign-in, and Kerberos (SPNEGO) sign-in | The operator, in `backend/.env` |

The mappings also apply to people who sign in through
[OIDC](configuration.md#single-sign-on-generic-oidc), when the identity provider
reports their groups. If your company already runs Keycloak or Entra ID in front
of its directory, you may not need the native LDAP sign-in at all. See
[Through an identity provider instead](#through-an-identity-provider-instead).

## Groups

A group is a named set of members inside one organization: *Finance*,
*Support team*, *Platform admins*. You share an agent, a skill, a collection, a
context file, a vault secret or an artifact with a group the same way you share
it with a person, from the resource's **Sharing** panel. One grant then reaches
everyone in the group.

A group grant reaches whoever is in the group **when access is checked**. Somebody
who joins the group next month reaches the resource; somebody who leaves stops
reaching it. There is nothing to revoke per person.

A group carries no role. What a member may do in the organization is still their
membership's role, and a group only adds the grants made to it. Effective access
stays the rule described in [Permissions](permissions.md#how-the-layers-combine):

```
effective access to one row = max(role scope, the person's grant, their groups' grants)
```

When a person reaches a row through several grants, the highest level wins. Read
through their own grant and edit through their group's is edit.

| Action | Who may |
|---|---|
| List groups and see who is in them | Any member of the organization |
| Create, rename or delete a group; add or remove people | `members:manage` |
| Share a resource with a group | Whoever may edit that resource |

Groups live on **Organizations → Members → Groups**. Only members of the
organization can be added, and removing somebody from the organization removes
them from all of its groups. Deleting a group deletes every grant made to it and
every directory mapping that names it.

## Directory group mappings

A mapping says what one directory group means inside one organization:

> Everyone in `CN=Finance,OU=Groups,DC=corp,DC=example,DC=com` is a **member**
> here, and is in the group **Finance**.

Mappings live on **Organizations → Members → Directory**. Reading them takes
`members:manage`. Creating or deleting one takes `members:manage` and
`roles:manage`, because a mapping both admits people and gives them a role.

The role is bounded the same way an invitation's is. You can only map a
directory group to a role your own role strictly outranks. Nobody can map a group
to `owner`, and an Admin cannot map a group to Admin. Deleting a mapping takes the
same authority, because it demotes everybody it placed.

### What happens at sign-in

Every time somebody signs in with LDAP, with Kerberos, or through OIDC with
[`OIDC_GROUPS_CLAIM`](#the-groups-claim-over-oidc) set, their directory groups
are read against every organization's mappings:

1. **An organization with a matching mapping** is joined if they are not a member
   yet, with the mapped role. The membership is marked **directory**.
2. **A directory membership** gets its role brought up to date with the mappings.
3. **They join the mapped groups**, and leave the directory-made group memberships
   no mapping names any more.
4. **A directory membership with no matching mapping left** is removed, together
   with the person's group memberships in that organization.

Groups are compared without regard to case or surrounding spaces, because every
directory compares them that way.

When several mappings match in one organization, the role is the first of these
that any of them names:

**admin → builder → operator → member → viewer**

Roles are not ordered by one line of authority. A builder and an operator each
hold something the other does not, so the order is stated here rather than worked
out.

### What the sync never touches

The sync only changes rows it made itself. Four rules follow from that:

- **A membership an administrator made keeps its role.** Somebody invited by hand
  keeps the role they were given, even if a mapping matches them. They still join
  the mapped groups.
- **Changing a directory member's role by hand takes the membership over.** It
  becomes a manual membership, and later sign-ins leave its role alone.
- **A group membership added by hand stays** when the directory would take the
  person out of that group.
- **An owner is never demoted or removed**, and no mapping can make one.
  Ownership moves through **Transfer ownership** only.

A personal organization is never joined through a mapping, and a mapping cannot
be created for one.

!!! warning "Deleting a mapping removes the people it placed"

    Removal happens at each person's **next sign-in**, not at once. To keep
    somebody after you delete the mapping that brought them in, change their role
    by hand first. That takes the membership over.

### Mappings admit new accounts

A mapping counts as an invitation. On an `invite_only` deployment, or one with an
allowed-domains list, a first sign-in whose groups match any organization's
mapping creates the account. Somebody who holds both `members:manage` and
`roles:manage` decided that everyone in that group belongs. A `closed` deployment
still refuses it. See [Who may register](deployment.md#who-may-register).

## Signing in with a directory account

Set `LDAP_URL` and the sign-in page offers a directory form. People type the
username they use everywhere else and their directory password. AgenticOS checks
the password with the standard two-step bind:

1. It searches `LDAP_USER_BASE_DN` with `LDAP_USER_FILTER`, using the service
   account (`LDAP_BIND_DN`), for exactly one account matching the username.
2. It binds **as that account** with the typed password. Only the directory checks
   the password. It is not stored, hashed or logged here.

The account is keyed on the directory's own stable identifier: `LDAP_ID_ATTRIBUTE`,
`objectGUID` on Active Directory and `entryUUID` on OpenLDAP and FreeIPA. It is not
keyed on the address, so a renamed person keeps their history. On their first
sign-in the account is created under the [sign-up
policy](deployment.md#who-may-register), and an existing account with the same
address is linked to it.

```bash
# backend/.env - Active Directory over LDAPS
LDAP_URL=ldaps://dc01.corp.example.com
LDAP_CA_CERT_FILE=/etc/ssl/certs/corp-ca.pem
LDAP_BIND_DN=CN=agenticos,OU=Service Accounts,DC=corp,DC=example,DC=com
LDAP_BIND_PASSWORD=...
LDAP_USER_BASE_DN=OU=Staff,DC=corp,DC=example,DC=com
LDAP_ID_ATTRIBUTE=objectGUID
```

```bash
# frontend - show the form on the sign-in page
OAUTH_PROVIDERS=ldap
LDAP_DISPLAY_NAME=Active Directory
```

Every setting and its default is in [Configuration](configuration.md#directory-sign-in-ldap).

### What the sign-in refuses

| Refused | Why |
|---|---|
| An empty password | An LDAP bind with a name and no password is an *unauthenticated* bind, which many servers accept (RFC 4513). It never reaches the directory |
| Two accounts matching one username | Binding as whichever came back first could sign one person in as another |
| A username carrying filter syntax | It is escaped (RFC 4515), so `*` finds nobody rather than everybody |
| An account with no address or no identifier | The account, the invitation and the sign-up policy are all keyed on them |
| `ldap://` without StartTLS | It sends every password in the clear. The process refuses to start unless `LDAP_ALLOW_PLAINTEXT=true` says so on purpose |

A wrong username and a wrong password get the same answer. A directory that is
down, a refused service account and a search the directory could not answer
(a wrong base DN, say) are reported as the directory being unavailable. They are
not reported as a wrong password, which would send every person in the company to
reset theirs.

The certificate is verified against the system trust store, or against
`LDAP_CA_CERT_FILE` for a company CA, and so is the host name. The sign-in is
rate-limited per address and per username, like the password sign-in.

### Groups from the directory

By default a person's groups are the DNs in their `memberOf` attribute. A directory
without `memberOf` can be searched instead: set `LDAP_GROUP_BASE_DN`, and
`LDAP_GROUP_FILTER` with `{dn}` or `{username}` in it. For Active Directory's
nested groups, search with the matching rule that follows the chain:

```bash
LDAP_GROUP_BASE_DN=OU=Groups,DC=corp,DC=example,DC=com
LDAP_GROUP_FILTER=(member:1.2.840.113556.1.4.1941:={dn})
```

To let only one group sign in at all, put it in `LDAP_USER_FILTER`:
`(&(objectClass=user)(sAMAccountName={username})(memberOf=CN=AgenticOS Users,OU=Groups,DC=corp,DC=example,DC=com))`.

## Integrated Windows sign-in (Kerberos)

On a domain-joined machine, a browser pointed at a host its policy trusts answers
`WWW-Authenticate: Negotiate` with a Kerberos ticket. With `KERBEROS_ENABLED=true`
the sign-in page offers a button that signs the person in with that ticket, and
nobody types a password.

The ticket names a principal, `jane@CORP.EXAMPLE.COM`. AgenticOS resolves it
through the directory above, with `LDAP_KERBEROS_FILTER`
(`(userPrincipalName={principal})` by default), to the **same account** the LDAP
password sign-in reaches. So Kerberos needs `LDAP_URL` as well, and the directory
decides the address and the groups the same way for both.

What it takes:

1. **An image built with the `kerberos` extra.** `gssapi` compiles against the
   system Kerberos libraries, so it is not in the default image:
   `docker build --build-arg EXTRAS="--extra kerberos" -f backend/Dockerfile .`
2. **A service principal and its keytab.** On Active Directory, create a service
   account, give it the SPN `HTTP/agenticos.corp.example.com`, and export a keytab
   with `ktpass`. Mount it into the backend container.
3. **The backend settings.**

    ```bash
    KERBEROS_ENABLED=true
    KERBEROS_KEYTAB=/etc/agenticos/http.keytab
    KERBEROS_SERVICE_PRINCIPAL=HTTP/agenticos.corp.example.com@CORP.EXAMPLE.COM
    ```

4. **The button**, with `kerberos` in the frontend's `OAUTH_PROVIDERS` and
   `KERBEROS_DISPLAY_NAME=Windows sign-in` if you want it named that way.
5. **Browser policy** that lets the browser negotiate with the API host. That
   means the local intranet zone on Windows, or `AuthServerAllowlist` for Chrome
   and Edge, or `network.negotiate-auth.trusted-uris` for Firefox.

The service principal must name the host the browser reaches the **API** on. That
is `PUBLIC_API_URL`, because the negotiation happens there, not on the console's
host.

A browser that cannot answer the challenge is sent straight back to the sign-in
page with a sentence saying so. That covers any machine outside the domain, and
any browser whose policy does not list the host. Only a ticket accepted in one
step is accepted at all. NTLM is not offered.

## Through an identity provider instead

If your company already puts an identity provider in front of its directory,
point AgenticOS at that instead, over [OIDC](configuration.md#single-sign-on-generic-oidc).
Use its groups claim for the mappings. The native LDAP and Kerberos sign-in are
then not needed. This is also the answer for multi-factor authentication, which
the native sign-in does not do.

**Keycloak** federates both. Under **User federation**, add an **LDAP** provider
for your directory, and switch on **Allow Kerberos authentication** there if you
want integrated sign-in. Its **group-ldap-mapper** brings the directory's groups
across. Then give the AgenticOS client a **Group Membership** mapper whose token
claim is `groups`, and set:

```bash
OIDC_ISSUER=https://id.corp.example.com/realms/staff
OIDC_GROUPS_CLAIM=groups
```

The mapping's directory group is then what Keycloak puts in the claim: the group
path, such as `/Finance`, or the bare name if **Full group path** is off.

**Microsoft Entra ID**, with groups synchronized from Active Directory, puts a
`groups` claim in the token once the app registration has one under **Token
configuration**. By default it carries each group's object id, and that id is
what you map.

### The groups claim over OIDC

`OIDC_GROUPS_CLAIM` names the claim that lists a person's groups. With it unset,
OIDC sign-ins leave memberships alone. With it set, each sign-in of the
deployment's own provider applies the mappings exactly as a directory sign-in
does. Google sign-in never does, because only the deployment's own provider is
trusted to say which of its groups somebody is in.

The claim is read from the ID token, or from the UserInfo endpoint when the token
does not carry it. A configured claim that is absent counts as **no groups**.
Keycloak and Okta leave an empty list out rather than send one, and somebody
removed from their last group has to lose what it gave them.

!!! warning "Entra ID group overage is refused"

    Past 200 groups, Entra ID sends a pointer to Microsoft Graph instead of the
    groups (`_claim_names`). Such a token does not say which groups the person is
    in, so the sign-in is refused with a sentence asking for the fix. Reading it
    as "no groups" would strip every membership the directory gave them, and
    ignoring it would keep ones it may have taken away. Configure the app
    registration to send **groups assigned to the application**.

## What this does not do yet

- **Nothing re-checks the directory between sign-ins.** Disabling an account in
  the directory stops its next sign-in, and the next sign-in is when mappings are
  re-read. A session already open lasts until its refresh token expires, which is
  `REFRESH_TOKEN_EXPIRE_MINUTES` and seven days by default. To end one sooner,
  deactivate the account under **Admin → Users**, which refuses it everywhere at
  once. There is no SCIM and no scheduled directory sync.
- **A directory account can still use the password reset and magic link.** They
  go to the account's address, like every other account's. If the directory is
  meant to be the only way in, keep those addresses under the company's own
  control, as you would for OIDC accounts.
- **No SAML.** A SAML-only identity provider can reach AgenticOS through Keycloak,
  which speaks SAML to it and OIDC to AgenticOS.
