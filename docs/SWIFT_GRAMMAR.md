# What the extractor sees

Notes on the `tree-sitter-swift` grammar, written down because three of these
produce a silently wrong graph rather than an error. Everything here was
verified against the parser before the extractor was written, and the tests in
`tests/test_extractor.py` pin each one.

## 1. `class_declaration` is overloaded

The node type covers **class, struct, enum, actor and extension**. They are
distinguished only by the `declaration_kind` field:

```
class_declaration  {declaration_kind=struct, name=type_identifier, body=class_body}
class_declaration  {declaration_kind=actor,  name=type_identifier, body=class_body}
class_declaration  {declaration_kind=enum,   name=type_identifier, body=enum_class_body}
class_declaration  {declaration_kind=extension, name=user_type,    body=class_body}
protocol_declaration {declaration_kind=protocol, name=type_identifier, body=protocol_body}
```

A walker that matches on node type alone files every struct, enum, actor and
extension in a repository as a class. Nothing errors; the graph is just wrong.
`protocol_declaration` is the one type-like declaration with its own node type.

Bodies also vary: `class_body`, `enum_class_body`, `protocol_body`.

An extension's `name` field is a `user_type`, not a `type_identifier`, so it
has to be reduced to a bare name (`Storage<Data>` → `Storage`).

## 2. `function_declaration` carries two `name` fields

One for the function name (`simple_identifier`) and one for the return type
(`user_type`):

```
function_declaration  {name=simple_identifier, name=user_type, body=function_body}
```

`child_by_field_name("name")` returns the first, which is what you want. But
`subscript_declaration` carries **only** the return-type `name`, so the same
call there yields a type where a name is expected. `init_declaration`'s name
is the literal `init` token, and `deinit_declaration` has no name field at
all. All three are named explicitly in `_member_name`.

`property_declaration`'s `name` is a `pattern`, whose `bound_identifier` field
holds the actual identifier.

## 3. `call_expression` has no `function` field

Its children are a `simple_identifier` or a `navigation_expression`, followed
by a `call_suffix`:

```
helper()                -> [simple_identifier "helper",       call_suffix "()"]
Service.make()          -> [navigation_expression "Service.make", call_suffix "()"]
self.other()            -> [navigation_expression "self.other",   call_suffix "()"]
items[id]               -> [simple_identifier "items",        call_suffix "[id]"]
```

Reaching for a `function` field returns `None` on every Swift call, producing
a graph with no `CALLS` edges and no error to say so.

The last line is a second trap inside the first: a **subscript access parses
as a call expression**. Treating it as a call wires every stored collection
into the call graph as a callee, so a `call_suffix` beginning with `[` is
skipped.

## Other constructs handled

| Construct | Node type | Notes |
|---|---|---|
| `import Foundation` | `import_declaration` | Names a *module*, not a file — becomes a `sym:` stub |
| `init` / `deinit` / `subscript` | `init_declaration`, `deinit_declaration`, `subscript_declaration` | Named explicitly |
| enum cases | `enum_entry` | Indexed as `property` — they are the enum's API surface |
| `typealias` / `associatedtype` | `typealias_declaration`, `associatedtype_declaration` | Both indexed as `typealias` |
| `#if DEBUG` | `directive` | Guarded declarations stay top-level siblings, so they index normally |
| `public` / `open` / `private` | `modifiers` → `visibility_modifier` | Recorded as node metadata |
| Doc comments | `comment`, `multiline_comment` | Two spellings — see below |
| `operator` / `precedencegroup` / `macro` | own node types | Parsed, not indexed |

## Doc comments come in two shapes

A `///` doc comment is a **run of consecutive `comment` siblings**, one per
line, so reading "the previous sibling" gets you the last line only. A
`/** … */` comment is a single `multiline_comment` sibling. `_extract_doc`
handles both, and walks backwards through the run for the first.

A comment sits before the declaration itself, not before its `modifiers`
child, so the anchor for the search is the declaration node.

## What is deliberately not modelled

**Type inference.** `let x = makeThing()` does not tell the graph what `x` is.
Resolving that needs SourceKit-LSP, a Swift toolchain and a project that
compiles. The tradeoff is stated in the CHANGELOG: deterministic extraction
that works on any checkout beats resolution that works only where the target
builds.

**Generic specialisation.** `Storage<Data>` and `Storage<String>` are the same
node. The graph is about declarations, not instantiations.

**Overloads.** Two `func send` at the same scope share a node ID. Swift
overloads on argument labels and types, and encoding those into an ID would
make it unstable against signature changes that do not change identity.
The symbol table treats such a name as ambiguous and declines to resolve
calls to it, which is why an unresolved call becomes an honest `sym:` stub.
