/**
 * Storage primitives for SampleKit.
 */
import Foundation
import SampleApp

/// A protocol describing a keyed repository.
public protocol Repository: AnyObject {
    associatedtype Item
    /// Number of stored items.
    var count: Int { get }
    func fetch(id: String) async throws -> Item
}

/// Marker protocol for auditable types.
public protocol Auditable {
    func audit() -> String
}

/// Generic in-memory storage.
open class Storage<T>: NSObject, Repository {
    public typealias Item = T
    private var items: [String: T] = [:]

    /// Live item count.
    public var count: Int { items.count }

    /// Fetch an item by identifier.
    public func fetch(id: String) async throws -> T {
        guard let value = items[id] else { throw StorageError.notFound }
        logAccess()
        return value
    }

    deinit { items.removeAll() }
}

/// Disk-backed storage.
public final class DiskStorage: Storage<Data>, Auditable {
    public override func fetch(id: String) async throws -> Data {
        return try await super.fetch(id: id)
    }

    public func audit() -> String { "disk" }

    class Inner {
        func deep() { logAccess() }
    }
}

/// Errors raised by storage.
public enum StorageError: Error {
    case notFound
    case invalid(reason: String)
}

/// Records an access for diagnostics.
func logAccess() {
    print("access")
}

/// Watches a path, and owns two nested types.
public struct PathMonitor {
    /// Shares its bare name with the standard library's `Result`.  From
    /// outside `PathMonitor` it answers only to `PathMonitor.Result`.
    enum Result {
        case available
        case timeout
    }

    /// Instantiated from inside the declaring scope, where the bare name is
    /// the one Swift resolves.
    struct Config {
        let timeout: Double
    }

    func makeConfig() -> Config {
        return Config(timeout: 1.0)
    }
}

/// Extends the *standard library's* `Result`.  `PathMonitor.Result` is not
/// visible by its bare name here, so this must not attach to it.
extension Result {
    var isStorageFailure: Bool { false }
}

/// `: Int` declares a raw value, not a conformance -- `Int` is not a protocol.
public enum Section: Int {
    case first
    case second
}

/// A raw type followed by a real conformance.
public enum Label: String, Auditable {
    case short

    public func audit() -> String { "label" }
}
