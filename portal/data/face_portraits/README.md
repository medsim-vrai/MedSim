# Character portraits (VRAI Faces)

Drop one **consented** image per character here, named by the character id:

    patel_attending.png
    riley_charge.jpg

Accepted: `.png` `.jpg` `.jpeg` `.webp`, up to 8 MB.

## Why this exists

The MedSim character card (`schemas/character.json`) carries no portrait. The
VRAI Faces avatar needs a source image to build face geometry, so the portal
attaches one here at launch — `GET /api/face/{id}/binding` inlines the file as
a `data:` URI in the bind payload (`portal/vrai_faces.py`).

If a character has no file here, the portal serves a neutral, non-photographic
placeholder silhouette and the avatar falls back to canonical face topology.

## Rules

- These are **facilitator-supplied, consented** images. The portal only ever
  reads local files — it never fetches, scrapes, or gathers facial images.
- Do not commit real faces to the repo. This folder is for local deployment
  assets; keep images out of version control unless they are licensed for it.
