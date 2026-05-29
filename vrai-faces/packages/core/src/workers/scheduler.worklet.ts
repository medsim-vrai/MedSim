// AudioWorklet ring buffer (Claude Code Guide §3.4). Bundled as a
// worklet asset by Vite — registered by audio_pipeline at boot.
//
// Type hint: AudioWorkletProcessor lives in the WebWorker lib at runtime.
// We avoid `any` and import via dom-types declared by tsconfig.
//
// NOTE: this file is loaded as a Worklet, not a module. Do not import
// from anywhere except its own scope.

declare const registerProcessor: (
  name: string,
  cls: new (...args: unknown[]) => AudioWorkletProcessor,
) => void;

declare abstract class AudioWorkletProcessor {
  readonly port: MessagePort;
  constructor();
  abstract process(
    inputs: Float32Array[][],
    outputs: Float32Array[][],
    parameters: Record<string, Float32Array>,
  ): boolean;
}

class TtsScheduler extends AudioWorkletProcessor {
  private ring = new Float32Array(48000 * 2); // 2 s @ 24 kHz stereo
  private writeIdx = 0;
  private readIdx = 0;

  constructor() {
    super();
    this.port.onmessage = (e: MessageEvent): void => {
      const data = e.data as Float32Array;
      this.enqueue(data);
    };
  }

  process(_inputs: Float32Array[][], outputs: Float32Array[][]): boolean {
    const out = outputs[0]?.[0];
    if (!out) return true;
    for (let i = 0; i < out.length; i++) {
      out[i] = this.readIdx === this.writeIdx
        ? 0
        : (this.ring[this.readIdx++] ?? 0);
      if (this.readIdx >= this.ring.length) this.readIdx = 0;
    }
    return true;
  }

  private enqueue(chunk: Float32Array): void {
    for (let i = 0; i < chunk.length; i++) {
      this.ring[this.writeIdx++] = chunk[i] ?? 0;
      if (this.writeIdx >= this.ring.length) this.writeIdx = 0;
    }
  }
}

registerProcessor('tts-scheduler', TtsScheduler);
