const STT_RATE = 16000;
const TTS_RATE = 24000;

const el = (id) => document.getElementById(id);
const setup = el("setup");
const room = el("room");
const statusLine = el("status");
const questionEl = el("question");
const timerEl = el("timer");
const transcriptEl = el("transcript");
let reportId = null;
const orb = el("orb");

let ws = null;
let micCtx = null;
let playCtx = null;
let player = null;
let capture = null;
let stream = null;
let deadline = 0;
let ticker = null;
let muted = false;
let currentTurn = "";

function log(speaker, text, opts = {}) {
  const row = document.createElement("div");
  row.className = `line ${speaker}` + (opts.interrupted ? " cut" : "");
  row.innerHTML = `<span class="who">${speaker === "interviewer" ? "Interviewer" : "You"}</span><span class="what"></span>`;
  row.querySelector(".what").textContent = text + (opts.interrupted ? " —" : "");
  transcriptEl.appendChild(row);
  transcriptEl.scrollTop = transcriptEl.scrollHeight;
}

function setStatus(text, mode) {
  statusLine.textContent = text;
  orb.dataset.mode = mode || "idle";
}

function startTimer(seconds) {
  deadline = Date.now() + seconds * 1000;
  clearInterval(ticker);
  ticker = setInterval(() => {
    const left = Math.max(0, Math.round((deadline - Date.now()) / 1000));
    timerEl.textContent = `${String(Math.floor(left / 60)).padStart(2, "0")}:${String(left % 60).padStart(2, "0")}`;
    if (left === 0) clearInterval(ticker);
  }, 250);
}

async function startInterview() {
  const cfg = {
    type: "start",
    role: el("role").value.trim() || "the role",
    duration_s: parseInt(el("duration").value, 10),
    topics: el("topics").value.split(",").map((s) => s.trim()).filter(Boolean),
    job_description: el("jd").value.trim(),
    resume: el("resume").value.trim(),
  };

  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        // Without echo cancellation the interviewer's own voice comes back in
        // through the mic and reads as a barge-in. Headphones are still the
        // reliable answer; this is the browser doing what it can.
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        channelCount: 1,
      },
    });
  } catch (err) {
    alert(
      "Microphone access was denied. The interview needs your microphone — " +
        "allow it in the address bar and try again."
    );
    return;
  }

  setup.hidden = true;
  room.hidden = false;
  setStatus("Connecting…", "idle");

  micCtx = new AudioContext({ sampleRate: STT_RATE });
  playCtx = new AudioContext({ sampleRate: TTS_RATE });
  await micCtx.audioWorklet.addModule("/static/capture-worklet.js");
  await playCtx.audioWorklet.addModule("/static/player-worklet.js");

  player = new AudioWorkletNode(playCtx, "player-processor");
  player.connect(playCtx.destination);
  player.port.onmessage = (e) => {
    if (e.data.type === "drained") send({ type: "playback_done" });
  };

  capture = new AudioWorkletNode(micCtx, "capture-processor");
  micCtx.createMediaStreamSource(stream).connect(capture);
  // Keep the node alive without routing the mic to the speakers.
  capture.connect(micCtx.createGain()).connect(micCtx.destination);

  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.binaryType = "arraybuffer";

  ws.onopen = () => {
    ws.send(JSON.stringify(cfg));
    capture.port.onmessage = (e) => {
      if (ws && ws.readyState === WebSocket.OPEN) ws.send(e.data.pcm);
      orb.style.setProperty("--level", Math.min(1, e.data.peak * 4).toFixed(2));
    };
  };

  ws.onmessage = (e) => {
    if (e.data instanceof ArrayBuffer) return playPcm(e.data);
    handle(JSON.parse(e.data));
  };

  ws.onclose = () => setStatus("Interview ended.", "idle");
  ws.onerror = () => setStatus("Connection problem.", "idle");
}

function playPcm(buffer) {
  const pcm = new Int16Array(buffer);
  const f32 = new Float32Array(pcm.length);
  for (let i = 0; i < pcm.length; i++) f32[i] = pcm[i] / 32768;
  player.port.postMessage({ type: "push", samples: f32.buffer }, [f32.buffer]);
}

function handle(msg) {
  switch (msg.type) {
    case "ready":
      startTimer(msg.duration_s);
      setStatus("Listening…", "listening");
      break;
    case "state":
      if (msg.floor === "interviewer") {
        setStatus("Interviewer speaking…", "speaking");
      } else {
        setStatus(muted ? "Muted" : "Listening…", muted ? "idle" : "listening");
      }
      break;
    case "interviewer_partial":
      currentTurn += msg.text;
      questionEl.textContent = currentTurn.trim();
      break;
    case "transcript_final":
      if (msg.speaker === "interviewer") {
        questionEl.textContent = msg.text;
        currentTurn = "";
      }
      log(msg.speaker, msg.text, { interrupted: msg.interrupted });
      break;
    case "interrupt":
      // Stop the audio already queued in the browser. Without this the
      // interviewer keeps talking for as long as the buffer is deep.
      player.port.postMessage({ type: "flush" });
      currentTurn = "";
      setStatus("Listening…", "listening");
      break;
    case "ended":
      clearInterval(ticker);
      questionEl.textContent = "Interview complete.";
      setStatus("Done", "idle");
      el("summary").hidden = false;
      el("summary").textContent = JSON.stringify(msg.summary, null, 2);
      teardown();
      break;
    case "report":
      // The server is building the assessment detached from this socket, so
      // the page is safe to open immediately — it polls until ready.
      reportId = msg.report_id;
      showReportLink();
      break;
    case "error":
      questionEl.textContent = msg.message;
      setStatus("Error", "idle");
      break;
  }
}

function send(payload) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(payload));
}

function teardown() {
  if (stream) stream.getTracks().forEach((t) => t.stop());
  if (micCtx) micCtx.close();
  clearInterval(ticker);
}

el("start").onclick = startInterview;
el("mute").onclick = () => {
  muted = !muted;
  capture.port.postMessage({ type: "mute", value: muted });
  el("mute").textContent = muted ? "Unmute" : "Mute";
  setStatus(muted ? "Muted" : "Listening…", muted ? "idle" : "listening");
};
el("end").onclick = () => {
  send({ type: "end" });
  teardown();
  setStatus("Interview ended.", "idle");
};
function showReportLink() {
  if (!reportId) return;
  const url = `/report/${reportId}`;
  // Surface it in the main question area as well as the button. A page
  // cached from before this feature existed has no #report element, and
  // returning quietly there is how the link went missing entirely.
  questionEl.innerHTML =
    `Interview complete. <a href="${url}" style="color:var(--accent)">See your report</a>`;
  let btn = el("report");
  if (!btn) {
    btn = document.createElement("button");
    btn.id = "report";
    (el("end")?.parentNode || document.body).appendChild(btn);
  }
  btn.hidden = false;
  btn.textContent = "See your report";
  btn.onclick = () => { window.location.href = url; };
  console.log("[intervueos] report ready:", url);
}

el("toggle-transcript").onclick = () => {
  const on = transcriptEl.hidden;
  transcriptEl.hidden = !on;
  el("toggle-transcript").textContent = on ? "Hide transcript" : "Show transcript";
};
