# Updater signature fixture

`payload.txt` is inert test data signed with a disposable Tauri signing key.
Only its public key and signature are committed. The private key was deleted.
The integration test serves it on loopback, uses the actual updater download
and signature verifier, and checks that modified bytes are refused. It never
installs the payload or restarts an application.
