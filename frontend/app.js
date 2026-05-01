'use strict';

const WS_URL = `ws://${location.host}/ws`;
const RECONNECT_DELAYS = [2000, 4000, 8000, 16000];

const $ = id => document.getElementById(id);

const state = {
  ws: null,
  isRecording: false,
  meetingStart: null,
  timerInterval: null,
  reconnectAttempt: 0,
  userScrolledUp: false,
};

// ── DOM refs ──────────────────────────────────────────────
const elTimer       = $('timer');
const elWordCount   = $('word-count');
const elStatusDot   = $('status-indicator');
const elTranscript  = $('transcript');
const elSummaryText = $('summary-text');
const elKeyPoints   = $('key-points');
const elTopics      = $('topics');
const elAnalyzing   = $('analyzing-indicator');
const elActionList  = $('action-list');
const elQaHistory   = $('qa-history');
const elQaInput     = $('qa-input');
const elQaSubmit    = $('qa-submit');
const elStartBtn    = $('start-btn');
const elStopBtn     = $('stop-btn');
const elMicSelect   = $('mic-select');
const elErrorBanner = $('error-banner');
const elErrorMsg    = $('error-msg');

// ── WebSocket ──────────────────────────────────────────────
function connect() {
  state.ws = new WebSocket(WS_URL);

  state.ws.onopen = () => {
    state.reconnectAttempt = 0;
    setStatus('idle');
  };

  state.ws.onmessage = e => {
    try { handleMessage(JSON.parse(e.data)); }
    catch { /* ignore malformed frames */ }
  };

  state.ws.onclose = () => {
    const delay = RECONNECT_DELAYS[Math.min(state.reconnectAttempt, RECONNECT_DELAYS.length - 1)];
    state.reconnectAttempt++;
    setTimeout(connect, delay);
  };

  state.ws.onerror = () => state.ws.close();
}

function send(obj) {
  if (state.ws && state.ws.readyState === WebSocket.OPEN) {
    state.ws.send(JSON.stringify(obj));
  }
}

// ── Message dispatcher ─────────────────────────────────────
function handleMessage(msg) {
  switch (msg.type) {
    case 'connected':       onConnected(msg); break;
    case 'meeting_started': onMeetingStarted(msg); break;
    case 'meeting_stopped': onMeetingStopped(msg); break;
    case 'transcript_update': onTranscriptUpdate(msg); break;
    case 'analysis_update': onAnalysisUpdate(msg); break;
    case 'qa_thinking':     onQaThinking(); break;
    case 'qa_result':       onQaResult(msg); break;
    case 'status_update':   onStatusUpdate(msg); break;
    case 'error':           onError(msg); break;
    case 'pong':            break;
  }
}

// ── Handlers ───────────────────────────────────────────────
function onConnected() {
  loadMicList();
}

function onMeetingStarted() {
  state.isRecording = true;
  state.meetingStart = Date.now();
  startTimer();
  setStatus('recording');
  elStartBtn.disabled = true;
  elStopBtn.disabled = false;
  elQaInput.disabled = false;
  elQaSubmit.disabled = false;
  elTranscript.textContent = '';
  elSummaryText.textContent = '等待分析…';
  elKeyPoints.innerHTML = '';
  elTopics.innerHTML = '';
  elActionList.innerHTML = '<li class="placeholder">尚無行動項目</li>';
  elQaHistory.innerHTML = '';
}

function onMeetingStopped() {
  state.isRecording = false;
  stopTimer();
  setStatus('idle');
  elStartBtn.disabled = false;
  elStopBtn.disabled = true;
  elQaInput.disabled = true;
  elQaSubmit.disabled = true;
}

function onTranscriptUpdate(msg) {
  const span = document.createElement('span');
  span.textContent = msg.new_text + ' ';
  elTranscript.appendChild(span);
  autoScroll(elTranscript);
}

function onAnalysisUpdate(msg) {
  elAnalyzing.classList.add('hidden');

  elSummaryText.textContent = msg.summary || '';

  elKeyPoints.innerHTML = '';
  (msg.key_points || []).forEach(pt => {
    const li = document.createElement('li');
    li.textContent = pt;
    elKeyPoints.appendChild(li);
  });

  elTopics.innerHTML = '';
  (msg.topics_discussed || []).forEach(t => {
    const chip = document.createElement('span');
    chip.className = 'topic-chip';
    chip.textContent = t;
    elTopics.appendChild(chip);
  });

  renderActionItems(msg.action_items || []);
}

function renderActionItems(items) {
  _lastActionItems = items;
  elActionList.innerHTML = '';
  if (!items.length) {
    elActionList.innerHTML = '<li class="placeholder">尚無行動項目</li>';
    return;
  }
  items.forEach(item => {
    const li = document.createElement('li');
    li.className = 'action-card';
    const ownerBadge = `<span class="owner-badge">${esc(item.owner)}</span>`;
    const due = item.due ? `<span class="due-chip">截止：${esc(item.due)}</span>` : '';
    li.innerHTML = `<div>${ownerBadge}<span class="task-text">${esc(item.task)}</span></div>${due}`;
    elActionList.appendChild(li);
  });
}

function onQaThinking() {
  const div = document.createElement('div');
  div.className = 'qa-item thinking';
  div.id = 'qa-thinking';
  div.textContent = '正在查詢…';
  elQaHistory.appendChild(div);
  autoScroll(elQaHistory);
}

function onQaResult(msg) {
  const thinking = $('qa-thinking');
  if (thinking) thinking.remove();

  const confClass = { high: 'conf-high', medium: 'conf-medium', low: 'conf-low' }[msg.confidence] || '';
  const div = document.createElement('div');
  div.className = 'qa-item';
  div.innerHTML = `
    <div class="qa-q">問：${esc(msg.question)}</div>
    <div class="qa-a">${esc(msg.answer)}</div>
    <div class="qa-meta">可信度：<span class="${confClass}">${esc(msg.confidence)}</span>
      ${msg.relevant_excerpt ? `｜依據：「${esc(msg.relevant_excerpt.slice(0, 80))}…」` : ''}
    </div>`;
  elQaHistory.appendChild(div);
  autoScroll(elQaHistory);
}

function onStatusUpdate(msg) {
  if (msg.is_analyzing) {
    elAnalyzing.classList.remove('hidden');
    setStatus('analyzing');
  } else if (msg.is_transcribing) {
    elAnalyzing.classList.add('hidden');
    setStatus('transcribing');
  } else if (msg.is_recording) {
    elAnalyzing.classList.add('hidden');
    setStatus('recording');
  }
  if (typeof msg.word_count === 'number') {
    elWordCount.textContent = `${msg.word_count} 詞`;
  }
}

function onError(msg) {
  elErrorMsg.textContent = `[${msg.code}] ${msg.message}`;
  elErrorBanner.classList.remove('hidden');
}

// ── Controls ───────────────────────────────────────────────
elStartBtn.addEventListener('click', () => {
  const deviceIndex = elMicSelect.value !== '' ? parseInt(elMicSelect.value, 10) : null;
  send({ type: 'start_meeting', device_index: deviceIndex });
});

elStopBtn.addEventListener('click', () => send({ type: 'stop_meeting' }));

elQaSubmit.addEventListener('click', submitQuestion);
elQaInput.addEventListener('keydown', e => { if (e.key === 'Enter') submitQuestion(); });

function submitQuestion() {
  const q = elQaInput.value.trim();
  if (!q) return;
  elQaInput.value = '';
  send({ type: 'ask_question', question: q });
}

// ── Export / Copy ──────────────────────────────────────────
let _lastActionItems = [];

$('copy-transcript-btn').addEventListener('click', () => {
  const text = elTranscript.textContent.trim();
  if (!text) return;
  navigator.clipboard.writeText(text).then(() => {
    const btn = $('copy-transcript-btn');
    const orig = btn.textContent;
    btn.textContent = '已複製！';
    setTimeout(() => { btn.textContent = orig; }, 1500);
  });
});

$('export-actions-btn').addEventListener('click', () => {
  if (!_lastActionItems.length) return;
  const lines = _lastActionItems.map(a =>
    `- [${a.owner}] ${a.task}${a.due ? `（截止：${a.due}）` : ''}`
  );
  const content = `行動項目\n${new Date().toLocaleString('zh-TW')}\n\n${lines.join('\n')}\n`;
  const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `action-items-${Date.now()}.txt`;
  a.click();
  URL.revokeObjectURL(url);
});

// ── Mic list ───────────────────────────────────────────────
async function loadMicList() {
  try {
    const devices = await fetch('/api/audio-devices').then(r => r.json());
    devices.forEach(d => {
      const opt = document.createElement('option');
      opt.value = d.index;
      opt.textContent = d.name;
      elMicSelect.appendChild(opt);
    });
  } catch { /* non-critical */ }
}

// ── Timer ──────────────────────────────────────────────────
function startTimer() {
  stopTimer();
  state.timerInterval = setInterval(() => {
    const elapsed = Math.floor((Date.now() - state.meetingStart) / 1000);
    const h = String(Math.floor(elapsed / 3600)).padStart(2, '0');
    const m = String(Math.floor((elapsed % 3600) / 60)).padStart(2, '0');
    const s = String(elapsed % 60).padStart(2, '0');
    elTimer.textContent = `${h}:${m}:${s}`;
  }, 1000);
}

function stopTimer() {
  if (state.timerInterval) clearInterval(state.timerInterval);
  state.timerInterval = null;
}

// ── Helpers ────────────────────────────────────────────────
function setStatus(s) {
  elStatusDot.className = `status-dot ${s}`;
}

function autoScroll(el) {
  const atBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 60;
  if (atBottom) el.scrollTop = el.scrollHeight;
}

function esc(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ── Keep-alive ─────────────────────────────────────────────
setInterval(() => send({ type: 'ping' }), 25000);

window.addEventListener('beforeunload', e => {
  if (state.isRecording) {
    e.preventDefault();
    e.returnValue = '會議正在進行中，確定要離開嗎？';
  }
});

// ── Init ───────────────────────────────────────────────────
connect();
