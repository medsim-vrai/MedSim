# Operator docs — how they stay current

Two deliverables, **each generated from one source of truth** so an update is edited in exactly one
place and never drifts between the printed guide and the in-app help.

| Deliverable | Source of truth (edit this) | Generated artifact (never hand-edit) |
|---|---|---|
| **Full operator guide** (print/PDF) | `operator-guide.html` | `MedSim-Operator-Guide.pdf` |
| **Support tool / FAQ** (in-app) | `faq.json` | `faq.html` |

`render.py` builds both: `python3 render.py` (or `render.py pdf` / `render.py faq`).

## The rule: docs are part of "done"

Any change that a user would notice — a **modification, update, upgrade, or a newly-fixed issue** —
updates these docs in the SAME change, before it ships. Concretely:

1. **Feature added / changed / removed** → edit the matching section of `operator-guide.html`. If it
   changes how something is done day-to-day, also add/adjust the relevant `faq.json` entry.
2. **Image / avatar / skin option changes** → update the *Modifying Characters & Images* section of the
   guide **and** the `Characters & images` FAQ entries (this is the most-asked area — keep it exact).
3. **A field issue is fixed** → add a `faq.json` entry under `Troubleshooting` (or the fitting category)
   phrased as the user's question + the resolution steps. If the fix changes operation, update the guide too.
4. **Bump the version + log it** (below), then **`python3 render.py`**, then commit / redeploy `support/`.

## Versioning

- `faq.json` → `meta.doc_version` is **semver**: PATCH = wording/new FAQ entry; MINOR = a new
  section/feature documented; MAJOR = a workflow the operator must relearn.
- Keep the guide's cover version in step with `faq.json` `meta.doc_version` (one version for the set).
- Each FAQ entry carries `last_updated` (and optional `status: current | deprecated`) so stale answers
  are visible. Set `meta.generated` to the build date.
- Record every change in `CHANGELOG.md`: `## <version> — <date>` + one line per guide/FAQ edit.

## `faq.json` entry shape

```json
{
  "id": "faq-mic-not-working",          // stable kebab id — never reuse or renumber
  "category": "Audio & speech",         // must be one of meta.categories
  "question": "The microphone isn't picking up the student — what do I check?",
  "answer": "Plain-English steps, in order. Reference on-screen names exactly.",
  "tags": ["microphone", "ptt", "permissions"],
  "last_updated": "2026-07-05",
  "status": "current"
}
```

## How it's integrated when deployed

- Ship the `support/` folder with the build. Serve `faq.html` behind a **Help / Support** link in the
  operator UI (it's self-contained — inline CSS+JS, searchable, no network calls), or have a support
  widget read `faq.json` directly and render its own list.
- The printed **PDF** goes to each site's binder / onboarding pack.
- Because both artifacts regenerate from the two sources, a deploy that includes an updated
  `faq.json` / `operator-guide.html` ships current help automatically — no separate doc pipeline.

## Suggested home in the repo

`medsim_v8/docs/support/` (source + generated + `render.py` + this file + `CHANGELOG.md`).
Add a one-line CI/pre-commit check that fails if `faq.json` changed but `meta.doc_version` didn't —
so the version bump is never forgotten.
