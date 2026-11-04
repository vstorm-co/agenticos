// The phone app runs from `lib.rs` through Tauri's mobile entry point; this is
// the same app on a laptop, for working on its pages without a phone.
fn main() {
    agenticos_mobile::run()
}
