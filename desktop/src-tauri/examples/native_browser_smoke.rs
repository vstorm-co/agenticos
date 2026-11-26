//! Exercise the same isolated rendering check shipped in native Arch packages.
#[path = "../src/native_browser.rs"]
mod native_browser;
#[path = "../src/native_browser_smoke.rs"]
mod native_browser_smoke;
const WINDOW: &str = "main";

fn main() {
    native_browser_smoke::run();
}
