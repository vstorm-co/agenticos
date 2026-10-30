//! What every AgenticOS shell - the desktop app, the phone app - agrees on about
//! reaching a deployment: the address a person typed, the sign-in that leaves for
//! the system browser, and the deep link that brings it back.
//!
//! Pure: no window, no plugin, nothing of Tauri's. The shells own their windows;
//! this owns the rules that make a sign-in theirs and nobody else's.

pub mod device;

use std::sync::Mutex;

use base64::Engine;
use sha2::{Digest, Sha256};
use url::Url;

/// The address a person typed, as the URL the webview will be pointed at.
///
/// A bare host is the common spelling (`agenticos.acme.com`), so a missing scheme
/// means `https`. Anything that is not a web address is refused here rather than
/// handed to the webview, which would show a platform error page with no way back
/// except the menu. So is plain `http` to anything but this machine: the console
/// posts the password and gets the token back on that connection, and a LAN is
/// exactly where somebody else can read it.
pub fn parse_server_url(typed: &str) -> Result<Url, String> {
    parse_server_url_with(typed, false)
}

/// `parse_server_url`, optionally letting plain `http` reach a private network
/// address - for a development build on a phone, whose development stack is on
/// the laptop beside it (`10.0.2.2` from the Android emulator). Never in a release.
pub fn parse_server_url_with(typed: &str, lan_http: bool) -> Result<Url, String> {
    let typed = typed.trim();
    if typed.is_empty() {
        return Err("Enter the address of your AgenticOS server.".to_owned());
    }
    let spelled = if typed.contains("://") {
        typed.to_owned()
    } else {
        format!("https://{typed}")
    };
    let url = Url::parse(&spelled).map_err(|_| format!("{typed} is not a web address."))?;
    if !matches!(url.scheme(), "http" | "https") {
        return Err(format!(
            "{typed} is not a web address: the shell opens http and https servers."
        ));
    }
    let Some(host) = url.host_str() else {
        return Err(format!("{typed} names no host."));
    };
    if url.scheme() == "http" && !is_loopback(host) && !(lan_http && is_private(host)) {
        return Err(format!(
            "{typed} would send your sign-in in the clear. Use https for a server that is not on this machine."
        ));
    }
    Ok(url)
}

/// Whether a host is this machine, where plain http cannot be read off a network.
pub fn is_loopback(host: &str) -> bool {
    let bare = host.trim_start_matches('[').trim_end_matches(']');
    bare == "localhost"
        || bare.ends_with(".localhost")
        || bare
            .parse::<std::net::IpAddr>()
            .is_ok_and(|ip| ip.is_loopback())
}

/// Whether a host is an address on a private network, which only a development build reaches over `http`.
fn is_private(host: &str) -> bool {
    match host.parse::<std::net::IpAddr>() {
        Ok(std::net::IpAddr::V4(ip)) => ip.is_private() || ip.is_link_local(),
        _ => false,
    }
}

/// A pairing code a phone scanned, and the console that showed it.
#[derive(Debug, PartialEq, Eq)]
pub struct Pairing {
    pub server: Url,
    pub code: String,
}

impl Pairing {
    /// Where the phone's webview goes to redeem it: the console's own page.
    pub fn redeem_url(&self) -> Url {
        let mut url = self.server.clone();
        url.set_path("/auth/pair");
        url.set_query(None);
        url.query_pairs_mut().append_pair("code", &self.code);
        url
    }
}

/// Read `agenticos://pair?server=…&code=…`, the link the console draws as a QR.
///
/// The server is held to the rules a typed address is - `https`, or this
/// machine - since a QR is text from anywhere: one that names a plain-http
/// server on the internet would sign the phone in over a line anyone can read.
pub fn pairing_link(link: &str, lan_http: bool) -> Result<Pairing, String> {
    let parsed =
        Url::parse(link).map_err(|_| "That code is not an AgenticOS pairing code.".to_owned())?;
    if parsed.scheme() != DEEP_LINK_SCHEME || parsed.host_str() != Some("pair") {
        return Err("That code is not an AgenticOS pairing code.".to_owned());
    }
    let value = |name: &str| {
        parsed
            .query_pairs()
            .find(|(key, _)| key == name)
            .map(|(_, value)| value.into_owned())
            .filter(|value| !value.is_empty())
    };
    let server = value("server").ok_or("That pairing code names no server.")?;
    let code = value("code").ok_or("That pairing code carries no code.")?;
    Ok(Pairing {
        server: parse_server_url_with(&server, lan_http)?,
        code,
    })
}

/// What a button outside the app asks for - on a live activity (the Dynamic
/// Island, the lock screen, Android's ongoing notification) or a shortcut (the
/// launcher, a Quick Settings tile, the Action Button) - as the link it opens
/// the app with.
#[derive(Debug, PartialEq, Eq)]
pub enum ActivityAction {
    /// Show this page of the console.
    Open(String),
    /// Approve or reject this approval, as the console's own buttons would.
    Decide { approval_id: String, approved: bool },
    /// Open the chat and start talking to its agent.
    Start(Mode),
}

/// How a shortcut starts the chat: a voice call, or dictation into the composer.
#[derive(Debug, PartialEq, Eq, Clone, Copy)]
pub enum Mode {
    Call,
    Dictate,
}

impl ActivityAction {
    /// Whether the person must be through the app's lock first: a decision is
    /// theirs to make, and a call or dictation opens the microphone.
    pub fn needs_presence(&self) -> bool {
        !matches!(self, ActivityAction::Open(_))
    }
}

/// Read `agenticos://activity/open?path=…`, `…/approve|reject?approval=…` and
/// `…/start?mode=call|dictate`.
///
/// A path must be one of the console's own, as a notification's must
/// (`is_console_path`): the link is text any app on the phone can fire, and
/// all it may do is move the console within itself, ask it to decide or open
/// the chat - the last two only after the app's own lock.
pub fn activity_link(link: &str) -> Option<ActivityAction> {
    let parsed = Url::parse(link).ok()?;
    if parsed.scheme() != DEEP_LINK_SCHEME || parsed.host_str() != Some("activity") {
        return None;
    }
    let value = |name: &str| {
        parsed
            .query_pairs()
            .find(|(key, _)| key == name)
            .map(|(_, value)| value.into_owned())
            .filter(|value| !value.is_empty())
    };
    match parsed.path() {
        "/open" => value("path")
            .filter(|path| is_console_path(path))
            .map(ActivityAction::Open),
        "/approve" | "/reject" => value("approval").map(|approval_id| ActivityAction::Decide {
            approval_id,
            approved: parsed.path() == "/approve",
        }),
        "/start" => match value("mode").as_deref() {
            Some("call") => Some(ActivityAction::Start(Mode::Call)),
            Some("dictate") => Some(ActivityAction::Start(Mode::Dictate)),
            _ => None,
        },
        _ => None,
    }
}

/// A path inside the console and nothing else: text from a server or a link
/// must not send the app's webview to another site.
pub fn is_console_path(path: &str) -> bool {
    path.starts_with('/')
        && !path.starts_with("//")
        && !path.contains('\\')
        && !path.contains("://")
}

/// What an organization's device management set for the app (#2305, #2097):
/// macOS managed preferences, Android app restrictions, a policy file on
/// Windows and Linux. Each shell reads its own source; the rules are here.
#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct ManagedPolicy {
    /// The organization's server.
    pub server: Option<Url>,
    /// Whether the person may point the app anywhere else.
    pub server_locked: bool,
    /// The phone app's biometric lock, forced on or off; `None` leaves it to the person.
    pub biometric_lock: Option<bool>,
}

impl ManagedPolicy {
    /// The policy as managed, its address held to the same rules as a typed one.
    pub fn new(
        server_url: Option<&str>,
        server_locked: bool,
        biometric_lock: Option<bool>,
        lan_http: bool,
    ) -> Result<Self, String> {
        let server = server_url
            .map(str::trim)
            .filter(|url| !url.is_empty())
            .map(|url| parse_server_url_with(url, lan_http))
            .transpose()?;
        Ok(Self {
            server_locked: server_locked && server.is_some(),
            server,
            biometric_lock,
        })
    }

    /// The server to open: the managed one while it is locked, otherwise the
    /// person's own choice, and the managed one before they have made one.
    pub fn server_for(&self, chosen: Option<&Url>) -> Option<Url> {
        if self.server_locked {
            return self.server.clone();
        }
        chosen.cloned().or_else(|| self.server.clone())
    }

    /// Whether the person may connect to this server.
    pub fn allows(&self, server: &Url) -> bool {
        !self.server_locked
            || self
                .server
                .as_ref()
                .is_some_and(|managed| managed.origin() == server.origin())
    }
}

/// The scheme the shell registers for a sign-in coming back from the browser.
///
/// Must match `DESKTOP_DEEP_LINK_SCHEME` on the deployment, which is what builds
/// the redirect - and `tauri.conf.json`, which is what registers it with the
/// operating system.
pub const DEEP_LINK_SCHEME: &str = "agenticos";

/// Whether this navigation is the *backend* starting an OAuth sign-in.
///
/// Google's authorization endpoint refuses an embedded user-agent
/// (`disallowed_useragent`), and the handoff it asks for is the system browser
/// with the result deep-linked back. So the shell watches for the start of the
/// flow rather than asking the console to behave differently in a window:
/// nothing in the frontend knows it is running here, and nothing has to (#1532).
///
/// Two things this checks that an earlier version did not, and each is a defect
/// it fixes:
///
/// **The origin, not only the path.** This webview deliberately permits
/// navigation to external sites during MCP consent, so a path-only predicate let
/// any page loaded in the window navigate to `https://its-host/api/oauth/x/login`
/// over and over - each cancelled navigation launching a browser window through
/// the privileged opener.
///
/// **The backend's URL, not the console's same-origin hop.** The console's
/// `/api/oauth/<provider>/login` is a proxy that attaches a staged invitation
/// read from an httpOnly cookie the system browser does not have (#1414).
/// Intercepting it sent the browser off without the invitation, so an invitee on
/// an `invite_only` deployment was refused. Letting the webview follow that hop
/// *itself* - where the cookie exists - and intercepting the redirect it produces
/// hands the browser a URL that already carries the handle.
pub fn is_oauth_start(server: Option<&Url>, url: &Url) -> bool {
    let Some(server) = server else {
        return false;
    };
    if url.origin() != server.origin() {
        return false;
    }
    let path = url.path();
    path.starts_with("/api/v1/oauth/") && path.ends_with("/login")
}

/// The same sign-in, marked as this shell's so the callback returns by deep link.
///
/// `client=desktop` is recorded in the session at the *start* and read at the
/// callback; the backend never takes it off the return, because it builds a
/// redirect out of it.
///
/// `desktop_nonce` carries the public S256 challenge of an app-held verifier.
/// The callback can be redeemed only with that private verifier. Without it any local process holding
/// a code from this deployment could invoke `agenticos://auth/callback?code=…`
/// and replace the webview's cookies with its own session - moving the person
/// into an account somebody else controls.
pub fn external_sign_in_url(url: &Url, nonce: &str) -> Url {
    let mut opened = url.clone();
    let kept: Vec<(String, String)> = url
        .query_pairs()
        .filter(|(name, _)| name != "client" && name != "desktop_nonce")
        .map(|(name, value)| (name.into_owned(), value.into_owned()))
        .collect();
    {
        let mut query = opened.query_pairs_mut();
        query.clear();
        for (name, value) in &kept {
            query.append_pair(name, value);
        }
        query.append_pair("client", "desktop");
        query.append_pair("desktop_nonce", &sign_in_challenge(nonce));
    }
    opened
}

/// The nonce of the sign-in this shell started, if one is still waiting.
///
/// One at a time, and replaced rather than queued: starting a second sign-in
/// abandons the first, which is what a person clicking the button again means.
#[derive(Default)]
pub struct PendingSignIn(pub Mutex<Option<String>>);

impl PendingSignIn {
    /// Unrelated links and invalid callbacks cannot cancel a pending sign-in.
    pub fn finish(&self, server: Option<&Url>, link: &str) -> Option<(Url, String)> {
        let mut pending = self.0.lock().ok()?;
        let destination = deep_link_return(server, pending.as_deref(), link)?;
        Some((destination, pending.take()?))
    }
}

/// S256 proof challenge; the verifier itself never leaves app memory in a URL.
pub fn sign_in_challenge(verifier: &str) -> String {
    base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(Sha256::digest(verifier.as_bytes()))
}

/// A validated callback exposes its verifier only to that code, once.
#[derive(Default)]
pub struct SignInProof(Mutex<Option<(String, String)>>);

impl SignInProof {
    pub fn remember(&self, destination: &Url, verifier: &str) -> Result<(), String> {
        let code = destination
            .query_pairs()
            .find(|(key, _)| key == "code")
            .map(|(_, value)| value.into_owned())
            .ok_or("Missing sign-in code")?;
        *self.0.lock().map_err(|e| e.to_string())? = Some((code, verifier.to_owned()));
        Ok(())
    }

    pub fn take(&self, code: &str) -> Result<String, String> {
        let mut proof = self.0.lock().map_err(|e| e.to_string())?;
        if !proof
            .as_ref()
            .is_some_and(|(pending, _)| constant_time_eq(pending, code))
        {
            return Err("No app sign-in is waiting for that code.".into());
        }
        proof
            .take()
            .map(|(_, verifier)| verifier)
            .ok_or_else(|| "The sign-in was already used.".into())
    }

    pub fn clear(&self) -> Result<(), String> {
        self.0.lock().map_err(|e| e.to_string())?.take();
        Ok(())
    }
}

/// Compare two nonces without leaking which byte differed.
///
/// A nonce is not a password and nothing here is timing-attackable in practice -
/// an attacker who can invoke the scheme can invoke it as often as they like.
/// It is still the comparison this repository uses for every value that decides
/// an authentication, and writing the other one invites the next reader to copy
/// it somewhere it does matter.
pub fn constant_time_eq(left: &str, right: &str) -> bool {
    let (left, right) = (left.as_bytes(), right.as_bytes());
    if left.len() != right.len() {
        return false;
    }
    left.iter()
        .zip(right)
        .fold(0u8, |acc, (a, b)| acc | (a ^ b))
        == 0
}

/// A fresh, unguessable nonce for one sign-in attempt.
pub fn mint_nonce() -> String {
    // Independent OS-random UUIDs provide more than 256 bits, hex-encoded.
    // The verifier stays within PKCE's 43–128 character range.
    format!(
        "{}{}{}",
        uuid::Uuid::new_v4().simple(),
        uuid::Uuid::new_v4().simple(),
        uuid::Uuid::new_v4().simple()
    )
}

/// Where the console window goes when the browser hands a sign-in back.
///
/// `agenticos://auth/callback?code=…` becomes `<server>/auth/callback?code=…`,
/// the page the console already has: it POSTs the single-use code to the BFF,
/// which swaps it for the token pair and sets the httpOnly cookies. The window's
/// cookie jar is the one that ends up signed in, which is the whole point of the
/// handoff - the browser that completed the flow has its own.
///
/// `None` for a link that is not a sign-in return, or one carrying no code, or
/// when no server has been chosen yet. A deep link is something any process on
/// the machine can fire, so what it is allowed to do is navigate to one path on
/// the server the *user* already configured - never to an address it names.
pub fn deep_link_return(server: Option<&Url>, expected: Option<&str>, link: &str) -> Option<Url> {
    let parsed = Url::parse(link).ok()?;
    if parsed.scheme() != DEEP_LINK_SCHEME {
        return None;
    }
    // `agenticos://auth/callback` parses `auth` as the host and `/callback` as
    // the path, which is why both are checked rather than the path alone.
    if parsed.host_str() != Some("auth") || parsed.path() != "/callback" {
        return None;
    }
    // The nonce this shell minted when it started the flow, echoed back through
    // the backend. Anyone on this machine can invoke a custom scheme, so without
    // it a local process holding a code from this deployment could hand the
    // window somebody else's session - and the window would accept it, because a
    // code is all the callback page needs.
    let returned = parsed
        .query_pairs()
        .find(|(name, _)| name == "desktop_nonce")
        .map(|(_, value)| value.into_owned());
    match (expected, returned.as_deref()) {
        (Some(mine), Some(theirs)) if constant_time_eq(&sign_in_challenge(mine), theirs) => {}
        _ => return None,
    }
    let code = parsed
        .query_pairs()
        .find(|(name, _)| name == "code")
        .map(|(_, value)| value.into_owned())?;
    if code.is_empty() {
        return None;
    }
    let mut destination = server?.clone();
    destination.set_path("/auth/callback");
    destination.set_query(None);
    destination.query_pairs_mut().append_pair("code", &code);
    Some(destination)
}

#[cfg(test)]
mod tests {
    use url::Url;

    use super::{
        activity_link, constant_time_eq, deep_link_return, external_sign_in_url, is_oauth_start,
        mint_nonce, pairing_link, parse_server_url, parse_server_url_with, sign_in_challenge,
        ActivityAction, ManagedPolicy, Mode, PendingSignIn, SignInProof,
    };

    fn url(spelled: &str) -> Url {
        Url::parse(spelled).expect("a test URL")
    }

    #[test]
    fn unrelated_links_preserve_the_pending_sign_in_until_a_valid_callback() {
        let pending = PendingSignIn::default();
        let verifier = mint_nonce();
        *pending.0.lock().unwrap() = Some(verifier.clone());
        let server = url("https://acme.example/");
        for link in [
            "agenticos://chat/new",
            "agenticos://activity/inbox",
            "agenticos://auth/callback?code=wrong&desktop_nonce=wrong",
        ] {
            assert!(pending.finish(Some(&server), link).is_none());
        }
        let callback = format!(
            "agenticos://auth/callback?code=mine&desktop_nonce={}",
            sign_in_challenge(&verifier)
        );
        let (destination, returned) = pending.finish(Some(&server), &callback).unwrap();
        assert_eq!(returned, verifier);
        assert_eq!(
            destination.as_str(),
            "https://acme.example/auth/callback?code=mine"
        );
        assert!(pending.finish(Some(&server), &callback).is_none());
    }

    #[test]
    fn a_sign_in_start_is_the_one_navigation_the_window_refuses() {
        let server = url("https://acme.example/");

        assert!(is_oauth_start(
            Some(&server),
            &url("https://acme.example/api/v1/oauth/google/login")
        ));
        assert!(is_oauth_start(
            Some(&server),
            &url("https://acme.example/api/v1/oauth/oidc/login?invitation_handle=abc")
        ));
    }

    #[test]
    fn the_providers_return_is_not_a_start_and_loads_in_the_window() {
        let server = url("https://acme.example/");

        assert!(!is_oauth_start(
            Some(&server),
            &url("https://acme.example/auth/callback?code=x")
        ));
        assert!(!is_oauth_start(
            Some(&server),
            &url("https://acme.example/api/v1/oauth/exchange")
        ));
        assert!(!is_oauth_start(
            Some(&server),
            &url("https://acme.example/login")
        ));
    }

    #[test]
    fn the_consoles_own_hop_is_followed_so_it_can_attach_the_invitation() {
        // `/api/oauth/...` is the frontend proxy, which reads a staged
        // invitation out of an httpOnly cookie the system browser does not
        // have (#1414). Intercepting it sent the browser off without the
        // invitation, and an invitee on an `invite_only` deployment was
        // refused; letting the webview follow it and catching the redirect it
        // produces hands the browser a URL that already carries the handle.
        let server = url("https://acme.example/");

        assert!(!is_oauth_start(
            Some(&server),
            &url("https://acme.example/api/oauth/google/login?flow=abc")
        ));
    }

    #[test]
    fn another_sites_sign_in_path_is_not_this_deployments() {
        // The window permits navigation to external sites during MCP consent,
        // so a path-only check let any loaded page launch browser windows
        // through the privileged opener, as often as it liked.
        let server = url("https://acme.example/");

        assert!(!is_oauth_start(
            Some(&server),
            &url("https://evil.example/api/v1/oauth/google/login")
        ));
        assert!(!is_oauth_start(
            Some(&server),
            &url("http://acme.example/api/v1/oauth/google/login")
        ));
        assert!(!is_oauth_start(
            None,
            &url("https://acme.example/api/v1/oauth/google/login")
        ));
    }

    #[test]
    fn the_browser_is_told_the_shell_started_it_and_which_attempt_this_is() {
        // Minted rather than written out, here and below. A literal in this
        // position is a hard-coded nonce to anything reading the tree, and it is
        // also the weaker test: a real one proves the value is carried through
        // rather than that one particular string is.
        let nonce = mint_nonce();
        let challenge = sign_in_challenge(&nonce);
        let opened = external_sign_in_url(
            &url("https://acme.example/api/v1/oauth/google/login"),
            &nonce,
        );

        assert_eq!(
            opened.as_str(),
            format!("https://acme.example/api/v1/oauth/google/login?client=desktop&desktop_nonce={challenge}")
        );
    }

    #[test]
    fn a_staged_invitation_survives_the_handoff() {
        let nonce = mint_nonce();
        let challenge = sign_in_challenge(&nonce);
        let opened = external_sign_in_url(
            &url("https://acme.example/api/v1/oauth/google/login?invitation_handle=abc123"),
            &nonce,
        );

        assert_eq!(
            opened.as_str(),
            format!(
                "https://acme.example/api/v1/oauth/google/login?invitation_handle=abc123&client=desktop&desktop_nonce={challenge}"
            )
        );
    }

    #[test]
    fn markers_the_page_already_carried_are_replaced_rather_than_doubled() {
        let stale = mint_nonce();
        let fresh = mint_nonce();
        let challenge = sign_in_challenge(&fresh);
        let opened = external_sign_in_url(
            &url(&format!(
                "https://acme.example/api/v1/oauth/google/login?client=desktop&desktop_nonce={stale}"
            )),
            &fresh,
        );

        assert_eq!(
            opened.as_str(),
            format!("https://acme.example/api/v1/oauth/google/login?client=desktop&desktop_nonce={challenge}")
        );
    }

    #[test]
    fn proof_is_bound_to_one_callback_and_is_never_carried_in_its_url() {
        let verifier = mint_nonce();
        assert_eq!(verifier.len(), 96);
        let challenge = sign_in_challenge(&verifier);
        assert_ne!(verifier, challenge);
        let link = format!("agenticos://auth/callback?code=issued&desktop_nonce={challenge}");
        let destination =
            deep_link_return(Some(&url("https://acme.example/")), Some(&verifier), &link).unwrap();
        assert!(!link.contains(&verifier));
        assert!(!destination.as_str().contains(&verifier));
        let proof = SignInProof::default();
        proof.remember(&destination, &verifier).unwrap();
        assert!(proof.take("another-code").is_err());
        assert_eq!(proof.take("issued").unwrap(), verifier);
        assert!(proof.take("issued").is_err());
        proof.remember(&destination, &verifier).unwrap();
        proof.clear().unwrap();
        assert!(proof.take("issued").is_err());
        assert_eq!(
            sign_in_challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"),
            "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
        );
    }

    #[test]
    fn every_attempt_gets_a_nonce_of_its_own() {
        assert_ne!(mint_nonce(), mint_nonce());
        assert!(mint_nonce().len() >= 32);
    }

    #[test]
    fn a_returned_code_goes_to_the_console_the_user_chose() {
        let server = url("https://acme.example/");

        let destination = deep_link_return(
            Some(&server),
            Some("n0nce"),
            &format!(
                "agenticos://auth/callback?code=abc123&desktop_nonce={}",
                sign_in_challenge("n0nce")
            ),
        )
        .expect("a URL");

        assert_eq!(
            destination.as_str(),
            "https://acme.example/auth/callback?code=abc123"
        );
    }

    #[test]
    fn a_code_this_shell_did_not_ask_for_is_refused() {
        // Any local process can invoke the scheme. Without the nonce, one
        // holding a code from this deployment could replace the window's
        // cookies with its own session and move the person into an account
        // somebody else controls.
        let server = url("https://acme.example/");

        assert!(deep_link_return(
            Some(&server),
            Some("mine"),
            "agenticos://auth/callback?code=abc&desktop_nonce=theirs"
        )
        .is_none());
        assert!(deep_link_return(
            Some(&server),
            Some("mine"),
            "agenticos://auth/callback?code=abc"
        )
        .is_none());
        assert!(deep_link_return(
            Some(&server),
            None,
            "agenticos://auth/callback?code=abc&desktop_nonce=anything"
        )
        .is_none());
    }

    #[test]
    fn a_deep_link_cannot_name_its_own_destination() {
        // Any process on the machine can fire one, so all it may do is send the
        // console to one path on the server already configured.
        let server = url("https://acme.example/");
        let mine = Some("n0nce");

        assert!(deep_link_return(Some(&server), mine, "agenticos://auth/callback").is_none());
        assert!(deep_link_return(
            Some(&server),
            mine,
            "agenticos://evil/callback?code=x&desktop_nonce=n0nce"
        )
        .is_none());
        assert!(deep_link_return(
            Some(&server),
            mine,
            "agenticos://auth/other?code=x&desktop_nonce=n0nce"
        )
        .is_none());
        assert!(deep_link_return(Some(&server), mine, "https://evil.example/?code=x").is_none());
        assert!(deep_link_return(Some(&server), mine, "not a url").is_none());
        assert!(deep_link_return(
            Some(&server),
            mine,
            "agenticos://auth/callback?code=&desktop_nonce=n0nce"
        )
        .is_none());
    }

    #[test]
    fn a_return_before_a_server_was_chosen_goes_nowhere() {
        assert!(deep_link_return(
            None,
            Some("n0nce"),
            "agenticos://auth/callback?code=abc&desktop_nonce=n0nce"
        )
        .is_none());
    }

    #[test]
    fn nonces_of_different_lengths_are_not_equal() {
        let one = mint_nonce();
        assert!(constant_time_eq(&one, &one.clone()));
        assert!(!constant_time_eq(&one, &mint_nonce()));
        assert!(!constant_time_eq(&one, &format!("{one}x")));
        assert!(!constant_time_eq("", "x"));
    }

    #[test]
    fn a_bare_host_is_opened_over_https() {
        assert_eq!(
            parse_server_url("agenticos.acme.com").unwrap().as_str(),
            "https://agenticos.acme.com/"
        );
    }

    #[test]
    fn a_scheme_and_port_are_kept_as_typed() {
        assert_eq!(
            parse_server_url(" http://localhost:3000 ")
                .unwrap()
                .as_str(),
            "http://localhost:3000/"
        );
    }

    #[test]
    fn an_empty_address_is_refused() {
        assert!(parse_server_url("   ").is_err());
    }

    #[test]
    fn a_scheme_the_webview_cannot_open_is_refused() {
        assert!(parse_server_url("ftp://files.acme.com").is_err());
    }

    #[test]
    fn a_scheme_with_no_host_is_refused() {
        assert!(parse_server_url("https://").is_err());
    }

    #[test]
    fn plain_http_is_allowed_on_this_machine_only() {
        for local in [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://[::1]:3000",
            "http://app.localhost",
        ] {
            assert!(parse_server_url(local).is_ok(), "{local}");
        }
        let refusal = parse_server_url("http://agenticos.acme.com").unwrap_err();
        assert!(refusal.contains("https"));
        assert!(parse_server_url("http://192.168.1.20:3000").is_err());
    }

    #[test]
    fn a_pairing_link_names_its_console_and_redeems_on_its_own_page() {
        let pairing = pairing_link(
            "agenticos://pair?server=https%3A%2F%2Facme.example&code=c0de",
            false,
        )
        .unwrap();
        assert_eq!(pairing.server.as_str(), "https://acme.example/");
        assert_eq!(
            pairing.redeem_url().as_str(),
            "https://acme.example/auth/pair?code=c0de"
        );
    }

    #[test]
    fn a_pairing_link_that_is_not_one_or_names_an_insecure_server_is_refused() {
        for link in [
            "https://acme.example/pair?code=x",
            "agenticos://auth/callback?code=x",
            "agenticos://pair?code=x",
            "agenticos://pair?server=https%3A%2F%2Facme.example",
            "agenticos://pair?server=http%3A%2F%2Facme.example&code=x",
            "not a link",
        ] {
            assert!(pairing_link(link, false).is_err(), "{link}");
        }
    }

    #[test]
    fn a_development_build_reaches_the_laptop_beside_it_over_http() {
        assert!(parse_server_url_with("http://10.0.2.2:3000", true).is_ok());
        assert!(parse_server_url_with("http://192.168.1.20:3000", true).is_ok());
        assert!(parse_server_url_with("http://10.0.2.2:3000", false).is_err());
        assert!(parse_server_url_with("http://acme.example", true).is_err());
        assert!(pairing_link(
            "agenticos://pair?server=http%3A%2F%2F10.0.2.2%3A3210&code=x",
            true
        )
        .is_ok());
    }

    #[test]
    fn an_activity_button_opens_a_console_page_or_decides_an_approval() {
        assert_eq!(
            activity_link("agenticos://activity/open?path=%2Fruns%3Ftab%3Dapprovals"),
            Some(ActivityAction::Open("/runs?tab=approvals".into()))
        );
        assert_eq!(
            activity_link("agenticos://activity/approve?approval=ap1"),
            Some(ActivityAction::Decide {
                approval_id: "ap1".into(),
                approved: true
            })
        );
        assert_eq!(
            activity_link("agenticos://activity/reject?approval=ap1"),
            Some(ActivityAction::Decide {
                approval_id: "ap1".into(),
                approved: false
            })
        );
    }

    #[test]
    fn a_shortcut_starts_a_call_or_dictation_and_only_once_unlocked() {
        assert_eq!(
            activity_link("agenticos://activity/start?mode=call"),
            Some(ActivityAction::Start(Mode::Call))
        );
        assert_eq!(
            activity_link("agenticos://activity/start?mode=dictate"),
            Some(ActivityAction::Start(Mode::Dictate))
        );
        assert!(ActivityAction::Start(Mode::Call).needs_presence());
        assert!(ActivityAction::Decide {
            approval_id: "ap1".into(),
            approved: true
        }
        .needs_presence());
        assert!(!ActivityAction::Open("/chat".into()).needs_presence());
    }

    #[test]
    fn a_managed_server_is_the_default_and_a_locked_one_the_only_one() {
        let ours = Url::parse("https://agenticos.acme.com/").unwrap();
        let elsewhere = Url::parse("https://other.example/").unwrap();

        let suggested = ManagedPolicy::new(Some("agenticos.acme.com"), false, None, false).unwrap();
        assert_eq!(suggested.server_for(None), Some(ours.clone()));
        assert_eq!(
            suggested.server_for(Some(&elsewhere)),
            Some(elsewhere.clone())
        );
        assert!(suggested.allows(&elsewhere));

        let locked =
            ManagedPolicy::new(Some("https://agenticos.acme.com"), true, Some(true), false)
                .unwrap();
        assert_eq!(locked.server_for(Some(&elsewhere)), Some(ours.clone()));
        assert!(locked.allows(&ours.join("login").unwrap()));
        assert!(!locked.allows(&elsewhere));
        assert_eq!(locked.biometric_lock, Some(true));
    }

    #[test]
    fn a_lock_with_no_server_locks_nothing_and_a_bad_address_is_refused() {
        let nothing = ManagedPolicy::new(Some("  "), true, None, false).unwrap();
        assert_eq!(nothing, ManagedPolicy::default());
        let anywhere = Url::parse("https://other.example/").unwrap();
        assert!(nothing.allows(&anywhere));
        assert_eq!(nothing.server_for(Some(&anywhere)), Some(anywhere));
        assert!(ManagedPolicy::new(Some("http://agenticos.acme.com"), true, None, false).is_err());
    }

    #[test]
    fn an_activity_link_cannot_leave_the_console_or_decide_nothing() {
        for link in [
            "agenticos://activity/start",
            "agenticos://activity/start?mode=record",
            "agenticos://activity/open?path=https%3A%2F%2Fevil.example",
            "agenticos://activity/open?path=%2F%2Fevil.example",
            "agenticos://activity/approve",
            "agenticos://activity/delete?approval=ap1",
            "agenticos://pair?code=x",
            "https://activity/open?path=%2Fruns",
        ] {
            assert_eq!(activity_link(link), None, "{link}");
        }
    }
}
