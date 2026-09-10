// Playback with instant flush. A queue of decoded chunks drained on the audio
// thread; `flush` empties it synchronously, which is what makes barge-in feel
// immediate rather than "the interviewer trails off".
class PlayerProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._queue = [];
    this._offset = 0;
    this._active = false;
    this.port.onmessage = (e) => {
      const m = e.data;
      if (m.type === "push") {
        this._queue.push(new Float32Array(m.samples));
        this._active = true;
      } else if (m.type === "flush") {
        this._queue.length = 0;
        this._offset = 0;
        this._active = false;
      }
    };
  }

  process(_inputs, outputs) {
    const out = outputs[0][0];
    if (!out) return true;
    let i = 0;

    while (i < out.length && this._queue.length) {
      const head = this._queue[0];
      const take = Math.min(out.length - i, head.length - this._offset);
      out.set(head.subarray(this._offset, this._offset + take), i);
      this._offset += take;
      i += take;
      if (this._offset >= head.length) {
        this._queue.shift();
        this._offset = 0;
      }
    }
    while (i < out.length) out[i++] = 0;

    if (this._active && this._queue.length === 0) {
      this._active = false;
      this.port.postMessage({ type: "drained" });
    }
    return true;
  }
}

registerProcessor("player-processor", PlayerProcessor);
