// Code-split: lazy imports for things not needed on first paint.
// Claude Code Guide §3.6.

export const lazyEmotion  = (): Promise<typeof import('../modules/emotion_driver')> =>
  import('../modules/emotion_driver');

export const lazyExport   = (): Promise<typeof import('../modules/avatar_exporter')> =>
  import('../modules/avatar_exporter');

export const lazyTts      = (): Promise<typeof import('../modules/tts_provider')> =>
  import('../modules/tts_provider');
