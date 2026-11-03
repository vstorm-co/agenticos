//! Use the desktop dependency graph, where the HTTP client and updater enable
//! different crypto providers, before any networking has initialized rustls.

#[path = "../src/tls.rs"]
mod tls;

#[test]
fn desktop_tls_initializes_before_the_first_device_connection() {
    assert!(rustls::crypto::CryptoProvider::get_default().is_none());
    tls::initialize();
    tls::initialize();

    let _websocket_tls = rustls::ClientConfig::builder()
        .with_root_certificates(rustls::RootCertStore::empty())
        .with_no_client_auth();
    reqwest::Client::builder().build().unwrap();

    let provider = rustls::crypto::CryptoProvider::get_default().unwrap();
    assert!(!provider.cipher_suites.is_empty());
}
