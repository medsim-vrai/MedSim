# M{NN} — {Module Title}

**Phase:** {Phase number — Phase theme}
**Status:** {NOT STARTED | IN PROGRESS | DONE}
**Blocked by:** {comma-separated module ids, or "none"}
**Blocks:** {comma-separated module ids, or "none"}
**Estimated effort:** {n days}

---

## 1. Purpose

> One paragraph. Why does this module exist? What capability does it
> deliver that earlier modules did not? What downstream module depends
> on this being correct?

## 2. Structure

> Files, classes, data shapes. Concrete enough that a fresh session
> can read this section and know where everything lives.

**Files:**
- `path/to/file.py` — {role}
- `path/to/another.py` — {role}

**Key dataclasses / functions:**
- `ClassName` — {one-line role}
- `function_name(args) -> ReturnType` — {one-line role}

## 3. Uses

> How the rest of the system calls this module. Concrete call sites
> from `server.py`, templates, other modules. List the entry points
> in order of how the user encounters them at runtime.

## 4. Functions (exported API surface)

> Public functions / classes / constants. Anything callable from
> outside this module. Mark internal helpers with a leading `_` and do
> not list them here.

| Symbol | Signature | Purpose |
|--------|-----------|---------|
| `foo`  | `foo(x: int) -> str` | … |

## 5. Limitations

> What this module deliberately does NOT do. Future maintainers read
> this before they "fix" a missing feature that is actually
> out-of-scope. Cite the Development_Plan section or the design
> rationale in P6.

- Does not …
- Does not …

## 6. Test status

| Test file | Asserts | Status | Last run |
|-----------|---------|--------|----------|
| `tests/v7/test_…py` | … | PASS / FAIL / PENDING | YYYY-MM-DD |

## 7. Change list

> Reverse chronological. One entry per material change. Each entry
> records date, brief description, files touched, and (when the change
> is finalized) the diff hash or commit ref.

| Date | Author | Change | Files |
|------|--------|--------|-------|
| YYYY-MM-DD | claude-code | Initial implementation | … |

## 8. Open questions / known issues

> Anything a future maintainer should think twice about before
> changing. Performance notes, race-condition risks, places where the
> design is provisional.

---

*Render this guide to PDF with: `pandoc M{NN}_*.md -o M{NN}_*.pdf` (or use the
project's preferred Markdown-to-PDF toolchain). Keep the Markdown as
the source of truth; regenerate the PDF on each material change.*
