// Microphone capture. Runs on the audio thread, so it never stutters when the
// main thread is busy rendering. Emits 80 ms of 16-bit PCM at a time, which is
// the chunk size Deepgram Flux is tuned for.
const CHUNK = 1280; // 80 ms @ 16 kHz

class CaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._buf = new Float32Array(CHUNK);
    this._n = 0;
    this._muted = false;
    this.port.onmessage = (e) => {
      if (e.data && e.data.type === "mute") this._muted = !!e.data.value;
    };
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || !input[0]) return true;
    const ch = input[0];

    for (let i = 0; i < ch.length; i++) {
      this._buf[this._n++] = this._muted ? 0 : ch[i];
      if (this._n === CHUNK) {
        const pcm = new Int16Array(CHUNK);
        let peak = 0;
        for (let j = 0; j < CHUNK; j++) {
          const s = Math.max(-1, Math.min(1, this._buf[j]));
          pcm[j] = s < 0 ? s * 0x8000 : s * 0x7fff;
          const a = Math.abs(s);
          if (a > peak) peak = a;
        }
        this.port.postMessage({ pcm: pcm.buffer, peak }, [pcm.buffer]);
        this._n = 0;
      }
    }
    return true;
  }
}

registerProcessor("capture-processor", CaptureProcessor);
