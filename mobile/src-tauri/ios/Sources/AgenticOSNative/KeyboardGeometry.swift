import Foundation
import CoreGraphics

/// Only a docked keyboard occludes the whole WebView. Floating and off-screen
/// keyboards must not turn a split-screen iPad window into a keyboard-sized page.
func keyboardAdjustedFrame(base: CGRect, keyboard: CGRect) -> CGRect {
  guard !keyboard.isNull, keyboard.intersects(base), keyboard.maxY >= base.maxY,
    keyboard.minX <= base.minX, keyboard.maxX >= base.maxX
  else { return base }
  return CGRect(
    x: base.minX, y: base.minY, width: base.width,
    height: max(0, min(base.maxY, keyboard.minY) - base.minY))
}
