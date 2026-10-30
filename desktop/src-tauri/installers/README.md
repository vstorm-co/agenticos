# Installer artwork

SVG files are editable sources. The macOS PNG is 1320×840 at 144 DPI for a
660×420 point Finder window. Native icons sit at (180, 180) and (480, 180).

Render using `rsvg-convert -w WIDTH -h HEIGHT source.svg -o output.png`.
Set macOS DPI using `sips -s dpiWidth 144 -s dpiHeight 144 output.png`.
Convert Windows artwork using `sips -s format bmp output.png --out output.bmp`.
Dimensions: NSIS sidebar 164×314, header 150×57; WiX dialog 493×312, banner 493×58.
Windows artwork contains only the brand; instructional text remains native and localized.

NSIS installs for the current user and follows the system's language: English,
Polish, German or Spanish. CI builds packages on each operating system.
Signing and notarization require the release environment's credentials.
