import Foundation

/// A point in two dimensions.
public struct Point: Equatable, Hashable {
    /// Horizontal offset.
    public var x: Double
    public var y: Double

    /// Distance to another point.
    public func distance(to other: Point) -> Double {
        return magnitude(x - other.x, y - other.y)
    }
}

/// An isolated counter.
public actor Counter {
    private var value = 0

    /// Bump the counter.
    public func increment() {
        value += 1
        logAccess()
    }
}

/// Adds string conversion to Point.
extension Point: CustomStringConvertible {
    public var description: String { "(\(x), \(y))" }

    /// Scale both components.
    public func scaled(by factor: Double) -> Point {
        return Point(x: x * factor, y: y * factor)
    }
}

/// Euclidean magnitude.
func magnitude(_ dx: Double, _ dy: Double) -> Double {
    return (dx * dx + dy * dy).squareRoot()
}

/// A callback alias.
public typealias Handler = (Int) -> Void

/// The canonical origin.
public let origin = Point(x: 0, y: 0)

#if DEBUG
/// Debug-only helper.
func debugDump() { magnitude(0, 0) }
#endif
