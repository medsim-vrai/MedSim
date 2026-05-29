import type { Lifecycle } from './shared';

export interface FaceIngestModule extends Lifecycle {
  /** Accept a portrait image and normalize it for the mesh builder. */
  ingest(input: File | Blob): Promise<NormalizedPortrait>;
}

export interface NormalizedPortrait {
  png: Blob;                          // square, RGB, no alpha
  width: number;
  height: number;
  faceBbox: { x: number; y: number; w: number; h: number };
  /** SHA-256 of the normalized PNG, for caching downstream. */
  hash: string;
}
