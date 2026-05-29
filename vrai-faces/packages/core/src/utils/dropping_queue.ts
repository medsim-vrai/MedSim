/**
 * Bounded queue with drop-oldest policy. Used for backpressure on
 * incoming VRAISpeechFrame packets (Claude Code Guide §3.5).
 */
export class DroppingQueue<T> {
  private buf: T[] = [];
  private dropped = 0;

  constructor(private readonly max: number) {
    if (max < 1) throw new Error(`DroppingQueue max must be >= 1, got ${max}`);
  }

  push(v: T): void {
    if (this.buf.length >= this.max) {
      this.buf.shift();
      this.dropped++;
    }
    this.buf.push(v);
  }

  popAll(): T[] {
    const out = this.buf;
    this.buf = [];
    return out;
  }

  size(): number { return this.buf.length; }
  dropCount(): number { return this.dropped; }
  resetDropCount(): void { this.dropped = 0; }
}
