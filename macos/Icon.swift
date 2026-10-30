import AppKit
let output = CommandLine.arguments[1]
let image = NSImage(size: NSSize(width: 1024, height: 1024))
image.lockFocus()
NSColor(calibratedRed: 0.04, green: 0.39, blue: 0.40, alpha: 1).setFill()
NSBezierPath(roundedRect: NSRect(x: 64, y: 64, width: 896, height: 896), xRadius: 190, yRadius: 190).fill()
if let symbol = NSImage(systemSymbolName: "books.vertical", accessibilityDescription: nil)?
    .withSymbolConfiguration(NSImage.SymbolConfiguration(pointSize: 500, weight: .regular)) {
    NSColor.white.set()
    let tinted = NSImage(size: symbol.size)
    tinted.lockFocus()
    symbol.draw(at: .zero, from: .zero, operation: .sourceOver, fraction: 1)
    NSColor.white.setFill()
    NSRect(origin: .zero, size: symbol.size).fill(using: .sourceAtop)
    tinted.unlockFocus()
    tinted.draw(in: NSRect(x: 260, y: 235, width: 504, height: 554))
}
image.unlockFocus()
let rep = NSBitmapImageRep(data: image.tiffRepresentation!)!
try rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: output))
