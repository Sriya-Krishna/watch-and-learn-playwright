const BACKEND_URL = 'http://localhost:8000';

const toggleBtn = document.getElementById('toggleBtn');
const statusEl = document.getElementById('status');
const resultsEl = document.getElementById('results');
const eventCountEl = document.getElementById('eventCount');
const copyBtn = document.getElementById('copyBtn');
const downloadBtn = document.getElementById('downloadBtn');
const sendBtn = document.getElementById('sendBtn');
const toastEl = document.getElementById('toast');

let isRecording = false;
let lastEvents = [];

// Restore state on popup open
chrome.storage.local.get(['isRecording', 'events'], (data) => {
  isRecording = data.isRecording || false;
  lastEvents = data.events || [];
  updateUI();
});

toggleBtn.addEventListener('click', () => {
  isRecording = !isRecording;
  if (isRecording) {
    // Clear previous events and start recording
    chrome.storage.local.set({ isRecording: true, events: [] });
    lastEvents = [];
    chrome.runtime.sendMessage({ action: 'startRecording' });
  } else {
    // Stop recording
    chrome.storage.local.set({ isRecording: false });
    chrome.runtime.sendMessage({ action: 'stopRecording' });
    // Fetch captured events
    chrome.storage.local.get(['events'], (data) => {
      lastEvents = data.events || [];
      updateUI();
    });
  }
  updateUI();
});

copyBtn.addEventListener('click', () => {
  navigator.clipboard.writeText(JSON.stringify(lastEvents, null, 2)).then(() => {
    showToast('Copied to clipboard!');
  });
});

downloadBtn.addEventListener('click', () => {
  const blob = new Blob([JSON.stringify(lastEvents, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `recording-${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.json`;
  a.click();
  URL.revokeObjectURL(url);
  showToast('Downloaded!');
});

sendBtn.addEventListener('click', async () => {
  sendBtn.disabled = true;
  sendBtn.textContent = 'Sending...';
  try {
    const res = await fetch(`${BACKEND_URL}/interpret`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ events: lastEvents })
    });
    const data = await res.json();
    sendBtn.textContent = 'Sent!';
    showToast(`Session: ${data.sessionId} — Opening...`);
    // Open the session page in a new tab
    chrome.tabs.create({ url: `${BACKEND_URL}/session/${data.sessionId}` });
  } catch (err) {
    sendBtn.textContent = 'Send to Interpreter';
    showToast('Error: Is the backend running?');
    console.error(err);
  } finally {
    setTimeout(() => {
      sendBtn.disabled = false;
      sendBtn.textContent = 'Send to Interpreter';
    }, 2000);
  }
});

function updateUI() {
  if (isRecording) {
    toggleBtn.textContent = 'Stop Recording';
    toggleBtn.classList.add('recording');
    statusEl.textContent = 'Recording...';
    statusEl.classList.add('recording');
    resultsEl.classList.remove('visible');
  } else {
    toggleBtn.textContent = 'Start Recording';
    toggleBtn.classList.remove('recording');
    statusEl.textContent = lastEvents.length > 0 ? 'Recording stopped' : 'Ready to record';
    statusEl.classList.remove('recording');
    if (lastEvents.length > 0) {
      resultsEl.classList.add('visible');
      eventCountEl.textContent = lastEvents.length;
    } else {
      resultsEl.classList.remove('visible');
    }
  }
}

function showToast(msg) {
  toastEl.textContent = msg;
  toastEl.style.display = 'block';
  setTimeout(() => { toastEl.style.display = 'none'; }, 3000);
}
