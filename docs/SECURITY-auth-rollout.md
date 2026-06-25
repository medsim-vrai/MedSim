# SECURITY — admin/instructor sign-in: rollout plan

**Status:** MVP shipped (role-as-label); REAL separation is a tracked rollout
item (task #94). **Logged:** 2026-06-25.

## What shipped now (MVP — by explicit decision)

The entry page (`portal/templates/login.html`) offers three seats — **Instructor**,
**Admin**, **Observer** — selected via a `role` field on the sign-in form. But:

- There is **one shared master vault password**. Any of the three seats is reached
  with the *same* password (`portal/auth.py` `issue_session_token(role=…)`; the
  role is sanitized to `_VALID_ROLES`).
- **Admin and Instructor have identical powers** (`require_instructor` accepts
  both; only `observer` is blocked from mutating routes). Admin is currently a
  **label + intent marker**, not an enforced privilege boundary.

⚠️ **This is NOT a real security boundary.** Anyone with the master password can
sign in as Admin. Do not represent admin/instructor as access control to a
customer until the work below is done.

## What "doing it for real" requires (rollout — task #94)

1. **Separate credentials per role** — `portal/credentials.py` must hold (at
   least) an admin password and an instructor password (distinct verifiers /
   derived keys), so the seat is determined by *which password unlocks*, not a
   form field. Bind the resolved role to the session at unlock time (drop the
   client-supplied `role` field for privilege; keep it only for observer-as-self
   downgrade if desired).
2. **`auth.require_admin`** — add it (mirror `require_instructor`) and **gate
   admin-only routes** behind it. Candidates: `/portal/credentials` (API-key
   management), any system/settings mutation, and future user management.
3. **Decide the real permission split** — the MVP chose "same powers." For
   rollout, pick what Instructor must NOT do (likely: change API keys / system
   settings / manage users). Update `require_instructor` vs `require_admin`
   gating accordingly. (See the FR-013b authoring routes + `/portal/credentials`.)
4. **Password management** — admin can rotate the instructor password; lockout /
   rotation story; never log or echo passwords.
5. **Tests** — wrong-seat password rejected; instructor blocked from admin-only
   routes (403); admin allowed; observer still read-only.

## Touch points
- `portal/auth.py` — roles, `issue_session_token`, `require_instructor`,
  `is_admin` (add `require_admin`).
- `portal/credentials.py` — single-password vault today; needs multi-credential.
- `portal/server.py` — `/login` POST (`role` field), `/initialize`; gate
  admin-only routes.
- `portal/templates/login.html` — the seat picker.
- Tests: `tests/v8/test_auth_roles.py`.
