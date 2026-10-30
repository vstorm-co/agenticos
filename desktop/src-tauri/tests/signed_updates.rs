//! Exercise the real updater transport and signature verification without installation.
use std::io::{Read, Write};
use std::net::TcpListener;
use std::time::{Duration, Instant};

use tauri::test::{mock_builder, mock_context, noop_assets};
use tauri_plugin_updater::UpdaterExt;

const PAYLOAD: &[u8] = include_bytes!("fixtures/updater/payload.txt");
const SIGNATURE: &str = include_str!("fixtures/updater/payload.txt.sig");
const PUBLIC_KEY: &str = include_str!("fixtures/updater/public.key");

#[tokio::test]
async fn the_updater_accepts_signed_bytes_and_refuses_tampered_downloads() {
    for tampered in [false, true] {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        listener.set_nonblocking(true).unwrap();
        let origin = format!("http://{}", listener.local_addr().unwrap());
        let metadata = serde_json::json!({
            "version":"999.0.0", "notes":"Local signature fixture",
            "url":format!("{origin}/download"), "signature":SIGNATURE.trim()
        })
        .to_string();
        let server = std::thread::spawn(move || {
            let deadline = Instant::now() + Duration::from_secs(8);
            let mut delivered = 0;
            while delivered < 2 && Instant::now() < deadline {
                let Ok((mut connection, _)) = listener.accept() else {
                    std::thread::sleep(Duration::from_millis(5));
                    continue;
                };
                connection.set_nonblocking(false).unwrap();
                connection.set_read_timeout(Some(Duration::from_secs(2))).unwrap();
                let mut request = [0; 4096];
                let read = connection.read(&mut request).unwrap();
                let download = request[..read].starts_with(b"GET /download ");
                let body: &[u8] = if download {
                    if tampered {
                        b"modified bytes"
                    } else {
                        PAYLOAD
                    }
                } else {
                    metadata.as_bytes()
                };
                write!(connection, "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n", body.len()).unwrap();
                connection.write_all(body).unwrap();
                delivered += 1;
            }
            delivered
        });
        let mut context = mock_context(noop_assets());
        context
            .config_mut()
            .plugins
            .0
            .insert("updater".into(), serde_json::json!({"pubkey":PUBLIC_KEY.trim()}));
        let app = mock_builder()
            .plugin(tauri_plugin_updater::Builder::new().pubkey(PUBLIC_KEY.trim()).build())
            .build(context)
            .unwrap();
        let updater = app
            .updater_builder()
            .endpoints(vec![format!("{origin}/latest.json").parse().unwrap()])
            .unwrap()
            .executable_path(std::env::temp_dir().join("AgenticOS.app/Contents/MacOS/agenticos-desktop"))
            .timeout(Duration::from_secs(3))
            .build()
            .unwrap();
        let update = updater.check().await.unwrap().unwrap();
        let result = update.download(|_, _| {}, || {}).await;
        if tampered {
            assert!(result.is_err(), "A modified update must be refused before installation");
        } else {
            assert_eq!(result.unwrap(), PAYLOAD);
        }
        assert_eq!(server.join().unwrap(), 2);
    }
}
