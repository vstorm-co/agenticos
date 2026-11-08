//! Exercise RUSTSEC-2024-0429 with optimized GLib; debug builds may conceal it.

use glib::variant::ToVariant;

#[test]
fn variant_string_iteration_remains_sound_when_optimized() {
    let array = ["first", "middle", "last"].to_variant();
    let mut iter = array.array_iter_str().expect("a string array");
    assert_eq!(iter.next(), Some("first"));
    assert_eq!(iter.next_back(), Some("last"));
    assert_eq!(iter.next(), Some("middle"));
    assert_eq!(iter.next(), None);
    assert_eq!(array.array_iter_str().unwrap().nth(1), Some("middle"));
    assert_eq!(array.array_iter_str().unwrap().nth_back(1), Some("middle"));
    assert_eq!(array.array_iter_str().unwrap().last(), Some("last"));
}
