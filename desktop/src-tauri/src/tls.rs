//! Select TLS cryptography before plugins or background connections can use it.

pub(crate) fn initialize() {
    // Reqwest enables AWS-LC while the updater enables ring. With both features,
    // rustls cannot choose automatically and the device WebSocket task panics.
    // A previously installed provider is already an explicit process-wide choice.
    let _ = rustls::crypto::ring::default_provider().install_default();
}
