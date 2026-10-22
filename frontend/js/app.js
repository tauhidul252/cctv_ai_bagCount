/**
 * BastaCount AI Frontend Application Logic
 */

let tripwire = null;
let ws = null;
let audioCtx = null;

// Synthesize pleasant notification chime on bag crossing
function playBeep(direction) {
  try {
    if (!audioCtx) {
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (audioCtx.state === 'suspended') {
      audioCtx.resume();
    }
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.connect(gain);
    gain.connect(audioCtx.destination);

    // Higher chime for IN, slightly lower chime for OUT
    osc.frequency.value = direction === 'IN' ? 880 : 520;
    osc.type = 'sine';

    gain.gain.setValueAtTime(0.12, audioCtx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 0.25);

    osc.start();
    osc.stop(audioCtx.currentTime + 0.25);
  } catch (e) {
    // Audio context may require prior user interaction
  }
}

let currentDuration = 300.0;
let isScrubberDragging = false;

document.addEventListener('DOMContentLoaded', () => {
  initFormPersistence();
  initDates();
  initTabs();
  initTripwire();
  initWebSocket();
  initStatusPolling();
  initVideoPlaybackControls();
  initControls();
  initQuickCameraBar();
  initNVRForm();
  initVideoUpload();
  initReports();
  initModal();
  initStreamRecovery();
  initModelSelector();
});

// Helper for local YYYY-MM-DD
function getLocalDateString(d = new Date()) {
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

// Format seconds into MM:SS
function formatVideoTime(secs) {
  if (isNaN(secs) || secs < 0) secs = 0;
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60);
  return `${m}:${s < 10 ? '0' : ''}${s}`;
}

// 0. Auto-Save & Restore Form Inputs
function initFormPersistence() {
  const PERSIST_FIELDS = [
    'quick-preset', 'quick-camera-url',
    'nvr-brand', 'nvr-mode', 'nvr-host', 'nvr-port',
    'nvr-user', 'nvr-pass', 'nvr-channel', 'nvr-stream-type',
    'direct-stream-url'
  ];

  PERSIST_FIELDS.forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    const saved = localStorage.getItem('bastacount_' + id);
    if (saved !== null && saved !== '') {
      el.value = saved;
    }
    const saveVal = () => {
      localStorage.setItem('bastacount_' + id, el.value);
    };
    el.addEventListener('input', saveVal);
    el.addEventListener('change', saveVal);
  });
}

// Date Picker Initialization with Default = TODAY
function initDates() {
  const todayStr = getLocalDateString();
  const startDateInput = document.getElementById('filter-start-date');
  const endDateInput = document.getElementById('filter-end-date');

  if (startDateInput && !startDateInput.value) startDateInput.value = todayStr;
  if (endDateInput && !endDateInput.value) endDateInput.value = todayStr;

  // Playback inputs default
  const pbStart = document.getElementById('playback-start');
  const pbEnd = document.getElementById('playback-end');
  const now = new Date();
  const hh = String(now.getHours()).padStart(2, '0');
  const mm = String(now.getMinutes()).padStart(2, '0');

  if (pbStart && !pbStart.value) pbStart.value = `${todayStr}T00:00`;
  if (pbEnd && !pbEnd.value) pbEnd.value = `${todayStr}T${hh}:${mm}`;

  // Quick preset buttons for Reports
  const btnToday = document.getElementById('btn-date-today');
  if (btnToday) {
    btnToday.addEventListener('click', () => {
      startDateInput.value = todayStr;
      endDateInput.value = todayStr;
      loadReports();
    });
  }

  const btnYest = document.getElementById('btn-date-yesterday');
  if (btnYest) {
    btnYest.addEventListener('click', () => {
      const y = new Date();
      y.setDate(y.getDate() - 1);
      const yStr = getLocalDateString(y);
      startDateInput.value = yStr;
      endDateInput.value = yStr;
      loadReports();
    });
  }

  const btn7Days = document.getElementById('btn-date-7days');
  if (btn7Days) {
    btn7Days.addEventListener('click', () => {
      const past = new Date();
      past.setDate(past.getDate() - 6);
      startDateInput.value = getLocalDateString(past);
      endDateInput.value = todayStr;
      loadReports();
    });
  }
}

// Auto-recover video feed if MJPEG disconnects
function initStreamRecovery() {
  const videoImg = document.getElementById('video-feed');
  if (videoImg) {
    videoImg.onerror = () => {
      console.warn('[Stream] Video feed interrupted. Auto-reconnecting in 1s...');
      setTimeout(() => {
        videoImg.src = '/api/stream/feed?t=' + Date.now();
      }, 1000);
    };
  }
}

// 1. Navigation Tabs
function initTabs() {
  const tabs = document.querySelectorAll('.nav-tab');
  const contents = document.querySelectorAll('.tab-content');

  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      tabs.forEach(t => t.classList.remove('active'));
      contents.forEach(c => c.classList.remove('active'));

      tab.classList.add('active');
      const targetId = tab.getAttribute('data-tab');
      document.getElementById(targetId).classList.add('active');

      if (targetId === 'live-tab' && tripwire) {
        setTimeout(() => tripwire.resizeCanvas(), 100);
      }
      if (targetId === 'reports-tab') {
        loadReports();
      }
    });
  });
}

// 2. Tripwire Canvas Initialization
function initTripwire() {
  tripwire = new TripwireCanvas('line-canvas', 'video-feed');

  // Load existing line from server
  fetch('/api/status')
    .then(r => r.json())
    .then(data => {
      if (data.line && data.line.start && data.line.end) {
        tripwire.setLine(data.line.start[0], data.line.start[1], data.line.end[0], data.line.end[1]);
      }
    })
    .catch(console.error);

  // Save line button
  document.getElementById('btn-save-line').addEventListener('click', async () => {
    const line = tripwire.getLine();
    try {
      const res = await fetch('/api/config/line', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(line)
      });
      const data = await res.json();
      showToast('Tripwire line calibration saved successfully!');
    } catch (e) {
      alert('Error saving line coordinates: ' + e);
    }
  });

  // Reset line button
  document.getElementById('btn-reset-line').addEventListener('click', () => {
    tripwire.setLine(520, 230, 220, 230);
  });
}

// 3. WebSocket Real-time Push
function initWebSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/ws/live`;
  ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    console.log('[WebSocket] Connected for live bag updates.');
  };

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      if (data.type === 'bag_counted') {
        updateHUDCounters(data.total_in, data.total_out, data.net_count);
        prependLiveEvent(data);
        playBeep(data.direction);
      } else if (data.type === 'counter_reset') {
        updateHUDCounters(0, 0, 0);
        const list = document.getElementById('event-feed-list');
        if (list) {
          list.innerHTML = '<div style="text-align: center; color: var(--text-muted); padding: 2rem;">Waiting for bag crossing events...</div>';
        }
        if (typeof loadReports === 'function') {
          loadReports();
        }
      }
    } catch (e) {
      console.error(e);
    }
  };

  ws.onclose = () => {
    // Reconnect after 3s
    setTimeout(initWebSocket, 3000);
  };
}

// 4. Polling Status for FPS and Sync
function initStatusPolling() {
  const poll = async () => {
    try {
      const res = await fetch('/api/status');
      if (res.ok) {
        const data = await res.json();
        updateHUDCounters(data.total_in, data.total_out, data.net_count);
        document.getElementById('val-fps').innerHTML = `${data.fps} <span style="font-size: 1rem; color: var(--text-secondary);">FPS</span>`;
        document.getElementById('source-indicator').textContent = `Source: ${data.source_type} (${data.source})`;

        const statusBadge = document.getElementById('status-text');
        if (data.is_running) {
          statusBadge.textContent = 'AI Pipeline Active';
          statusBadge.parentElement.style.color = 'var(--accent-in)';
        } else {
          statusBadge.textContent = 'Pipeline Stopped';
          statusBadge.parentElement.style.color = 'var(--accent-out)';
        }

        // Update Quick Camera Connection Status
        const tag = document.getElementById('quick-conn-status');
        const label = document.getElementById('quick-conn-label');
        if (tag && label) {
          tag.className = 'conn-status-tag ' + (data.connection_state ? data.connection_state.toLowerCase() : 'demo');
          if (data.connection_state === 'CONNECTED') {
            label.textContent = `🟢 Live Camera Connected (${data.source})`;
          } else if (data.connection_state === 'CONNECTING') {
            label.textContent = `🟡 Connecting to Camera...`;
          } else if (data.connection_state === 'ERROR') {
            label.textContent = `🔴 Offline: ${data.last_error || 'Check RTSP URL'}`;
          } else {
            label.textContent = `Demo Simulation (Active)`;
          }
        }

        // Update Video Player Scrubber & Timeline
        const playPauseIcon = document.getElementById('play-pause-icon');
        if (playPauseIcon) {
          playPauseIcon.textContent = data.is_paused ? '▶' : '❚❚';
        }

        if (!isScrubberDragging && data.is_seekable) {
          currentDuration = data.duration || 300;
          const curTime = data.current_time || 0;
          const ratio = Math.max(0, Math.min(1, curTime / (currentDuration || 1)));

          const prog = document.getElementById('scrubber-progress');
          const thumb = document.getElementById('scrubber-thumb');
          const curText = document.getElementById('current-time-text');
          const durText = document.getElementById('duration-text');

          if (prog) prog.style.width = (ratio * 100) + '%';
          if (thumb) thumb.style.left = (ratio * 100) + '%';
          if (curText) curText.textContent = formatVideoTime(curTime);
          if (durText) durText.textContent = formatVideoTime(currentDuration);
        }
      }
    } catch (e) {}
  };

  poll();
  setInterval(poll, 1000);
}

// 4b. YouTube-Style Video Player Playback & Scrubber Controls
function initVideoPlaybackControls() {
  const playPauseBtn = document.getElementById('btn-play-pause');
  const playPauseIcon = document.getElementById('play-pause-icon');
  const skipBackBtn = document.getElementById('btn-skip-back');
  const skipFwdBtn = document.getElementById('btn-skip-forward');
  const scrubberContainer = document.getElementById('scrubber-container');
  const scrubberProgress = document.getElementById('scrubber-progress');
  const scrubberThumb = document.getElementById('scrubber-thumb');
  const scrubberTooltip = document.getElementById('scrubber-tooltip');
  const speedSelect = document.getElementById('playback-speed-select');
  const fullscreenBtn = document.getElementById('btn-fullscreen');
  const videoWrapper = document.getElementById('video-wrapper');

  if (!playPauseBtn || !scrubberContainer) return;

  // Play / Pause Toggle
  playPauseBtn.addEventListener('click', async () => {
    try {
      const res = await fetch('/api/stream/pause', { method: 'POST' });
      const data = await res.json();
      playPauseIcon.textContent = data.paused ? '▶' : '❚❚';
      showToast(data.paused ? 'Video Paused (❚❚)' : 'Video Playing (▶)');
    } catch (e) {
      console.error(e);
    }
  });

  // Skip Back 5s
  skipBackBtn.addEventListener('click', async () => {
    try {
      await fetch('/api/stream/seek', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ delta: -5.0 })
      });
      showToast('⏪ -5s');
    } catch (e) {}
  });

  // Skip Forward 5s
  skipFwdBtn.addEventListener('click', async () => {
    try {
      await fetch('/api/stream/seek', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ delta: 5.0 })
      });
      showToast('5s ⏩');
    } catch (e) {}
  });

  // Scrubber Seeking & Dragging
  const updateScrubberVisual = (e) => {
    const rect = scrubberContainer.getBoundingClientRect();
    const clientX = e.touches ? e.touches[0].clientX : e.clientX;
    const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    scrubberProgress.style.width = (ratio * 100) + '%';
    scrubberThumb.style.left = (ratio * 100) + '%';

    const previewTime = ratio * (currentDuration || 300);
    scrubberTooltip.textContent = formatVideoTime(previewTime);
    scrubberTooltip.style.left = (ratio * 100) + '%';
    scrubberTooltip.style.display = 'block';

    const curText = document.getElementById('current-time-text');
    if (curText) curText.textContent = formatVideoTime(previewTime);

    return previewTime;
  };

  const applySeek = async (targetSec) => {
    try {
      await fetch('/api/stream/seek', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ time: targetSec })
      });
    } catch (e) {}
  };

  scrubberContainer.addEventListener('mousedown', (e) => {
    isScrubberDragging = true;
    scrubberContainer.classList.add('dragging');
    const targetSec = updateScrubberVisual(e);
    applySeek(targetSec);
  });

  window.addEventListener('mousemove', (e) => {
    if (isScrubberDragging) {
      const targetSec = updateScrubberVisual(e);
      applySeek(targetSec);
    }
  });

  window.addEventListener('mouseup', () => {
    if (isScrubberDragging) {
      isScrubberDragging = false;
      scrubberContainer.classList.remove('dragging');
      scrubberTooltip.style.display = 'none';
    }
  });

  scrubberContainer.addEventListener('mouseenter', () => {
    scrubberTooltip.style.display = 'block';
  });

  scrubberContainer.addEventListener('mouseleave', () => {
    if (!isScrubberDragging) {
      scrubberTooltip.style.display = 'none';
    }
  });

  scrubberContainer.addEventListener('mousemove', (e) => {
    if (!isScrubberDragging) {
      const rect = scrubberContainer.getBoundingClientRect();
      const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
      const previewTime = ratio * (currentDuration || 300);
      scrubberTooltip.textContent = formatVideoTime(previewTime);
      scrubberTooltip.style.left = (ratio * 100) + '%';
      scrubberTooltip.style.display = 'block';
    }
  });

  // Touch support for mobile/tablets
  scrubberContainer.addEventListener('touchstart', (e) => {
    isScrubberDragging = true;
    scrubberContainer.classList.add('dragging');
    const targetSec = updateScrubberVisual(e);
    applySeek(targetSec);
  });

  window.addEventListener('touchmove', (e) => {
    if (isScrubberDragging) {
      const targetSec = updateScrubberVisual(e);
      applySeek(targetSec);
    }
  });

  window.addEventListener('touchend', () => {
    if (isScrubberDragging) {
      isScrubberDragging = false;
      scrubberContainer.classList.remove('dragging');
      scrubberTooltip.style.display = 'none';
    }
  });

  // Playback speed
  speedSelect.addEventListener('change', async (e) => {
    const val = parseFloat(e.target.value);
    await fetch('/api/stream/speed', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ speed: val })
    });
    showToast(`Speed: ${val}x`);
  });

  // Fullscreen
  fullscreenBtn.addEventListener('click', () => {
    if (!document.fullscreenElement) {
      videoWrapper.requestFullscreen().catch(console.error);
    } else {
      document.exitFullscreen().catch(console.error);
    }
  });

  // Keyboard Shortcuts: Space (Play/Pause), Left Arrow (-5s), Right Arrow (+5s), F (Fullscreen)
  window.addEventListener('keydown', (e) => {
    if (['INPUT', 'SELECT', 'TEXTAREA'].includes(e.target.tagName)) return;

    if (e.code === 'Space') {
      e.preventDefault();
      playPauseBtn.click();
    } else if (e.code === 'ArrowLeft') {
      e.preventDefault();
      skipBackBtn.click();
    } else if (e.code === 'ArrowRight') {
      e.preventDefault();
      skipFwdBtn.click();
    } else if (e.code === 'KeyF') {
      fullscreenBtn.click();
    }
  });
}

function initQuickCameraBar() {
  const presetSelect = document.getElementById('quick-preset');
  const urlInput = document.getElementById('quick-camera-url');
  const connectBtn = document.getElementById('btn-quick-connect');

  const presetExamples = {
    hikvision: 'rtsp://admin:12345@192.168.1.64:554/Streaming/Channels/101',
    dahua: 'rtsp://admin:admin123@192.168.1.108:554/cam/realmonitor?channel=1&subtype=0',
    cp_plus: 'rtsp://admin:admin123@192.168.1.250:554/cam/realmonitor?channel=1&subtype=0',
    uniview: 'rtsp://admin:123456@192.168.1.13:554/unicast/c1/s0/live',
    demo: 'demo',
    custom: ''
  };

  presetSelect.addEventListener('change', () => {
    const val = presetSelect.value;
    if (presetExamples[val] !== undefined) {
      urlInput.value = presetExamples[val];
      urlInput.placeholder = presetExamples[val] || 'rtsp://user:pass@ip:554/...';
    }
  });

  connectBtn.addEventListener('click', async () => {
    const url = urlInput.value.trim() || (presetSelect.value === 'demo' ? 'demo' : '');
    if (!url) {
      alert('অনুগ্রহ করে আপনার সিসিটিভি ক্যামেরার RTSP URL অথবা IP অ্যাড্রেস লিখুন।\nউদাহরণ: rtsp://admin:password@192.168.1.100:554/Streaming/Channels/101');
      return;
    }

    const tag = document.getElementById('quick-conn-status');
    const label = document.getElementById('quick-conn-label');
    if (tag && label) {
      tag.className = 'conn-status-tag connecting';
      label.textContent = 'Connecting to camera...';
    }

    try {
      const res = await fetch('/api/stream/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source: url,
          source_type: url === 'demo' ? 'demo' : 'rtsp',
          session_name: url === 'demo' ? 'Demo Simulation' : `CCTV Camera (${url})`
        })
      });
      if (res.ok) {
        showToast('Camera connection initiated!');
      } else {
        alert('Failed to start stream.');
      }
    } catch (e) {
      alert('Error connecting: ' + e);
    }
  });

  const demoBtn = document.getElementById('btn-switch-demo');
  if (demoBtn) {
    demoBtn.addEventListener('click', async () => {
      presetSelect.value = 'demo';
      urlInput.value = 'demo';
      localStorage.setItem('bastacount_quick-preset', 'demo');
      localStorage.setItem('bastacount_quick-camera-url', 'demo');

      const res = await fetch('/api/stream/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source: 'demo',
          source_type: 'demo',
          session_name: 'Demo Simulation'
        })
      });
      if (res.ok) {
        showToast('Switched to simulated demo bag counting!');
      }
    });
  }
}

function updateHUDCounters(inCount, outCount, netCount) {
  document.getElementById('val-in').textContent = inCount;
  document.getElementById('val-out').textContent = outCount;
  document.getElementById('val-net').textContent = netCount;
}

function prependLiveEvent(item) {
  const list = document.getElementById('event-feed-list');
  if (list.children.length === 1 && list.children[0].textContent.includes('Waiting')) {
    list.innerHTML = '';
  }

  const card = document.createElement('div');
  card.className = 'event-card';
  const badgeClass = item.direction.toLowerCase();

  const countBadge = (item.count && item.count > 1) ? ` (+${item.count} বস্তা STACKED)` : ` (+${item.count || 1} বস্তা)`;
  const notesText = item.notes ? `${item.notes} • ` : '';

  card.innerHTML = `
    <div class="event-left">
      <span class="event-badge ${badgeClass}">${item.direction}</span>
      <div class="event-info">
        <p>Track #${item.track_id} <span style="color: var(--accent-cyan); font-weight: 700;">${countBadge}</span></p>
        <span style="font-size: 0.75rem; color: var(--text-secondary);">${notesText}${item.timestamp}</span>
      </div>
    </div>
    ${item.snapshot ? `<img class="event-thumb" src="${item.snapshot}" onclick="openModal('${item.snapshot}', '${item.direction}', '${item.track_id}', '${item.timestamp}')" title="Click to inspect snapshot" />` : ''}
  `;

  list.insertBefore(card, list.firstChild);

  // Keep max 25 items
  if (list.children.length > 25) {
    list.removeChild(list.lastChild);
  }
}

// 5. Controls
function initControls() {
  const resetBtn = document.getElementById('btn-reset-counters');
  if (resetBtn) {
    resetBtn.addEventListener('click', async () => {
      if (confirm('Are you sure you want to reset all counts and crossing data to 0? (সব কাউন্টার এবং রেকর্ড ০ করতে চান?)')) {
        try {
          const res = await fetch('/api/stream/reset-counter', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ clear_database: true })
          });
          if (res.ok) {
            updateHUDCounters(0, 0, 0);
            const list = document.getElementById('event-feed-list');
            if (list) {
              list.innerHTML = '<div style="text-align: center; color: var(--text-muted); padding: 2rem;">Waiting for bag crossing events...</div>';
            }
            if (typeof loadReports === 'function') {
              loadReports();
            }
            showToast('All counters and records reset to 0! (কাউন্টার ও রেকর্ড সফলভাবে রিসেট হয়েছে)');
          } else {
            showToast('Reset failed. Please try again.');
          }
        } catch (e) {
          alert('Failed to reset: ' + e);
        }
      }
    });
  }

  const stopBtn = document.getElementById('btn-stop-stream');
  if (stopBtn) {
    stopBtn.addEventListener('click', async () => {
      await fetch('/api/stream/stop', { method: 'POST' });
      showToast('Stream stopped.');
    });
  }
}

// 6. NVR Form Handler
function initNVRForm() {
  const nvrForm = document.getElementById('nvr-form');
  const nvrMode = document.getElementById('nvr-mode');
  const playbackFields = document.getElementById('playback-fields');
  const generatedUrlInput = document.getElementById('nvr-generated-url');

  nvrMode.addEventListener('change', () => {
    playbackFields.style.display = nvrMode.value === 'playback' ? 'block' : 'none';
    updatePreviewUrl();
  });

  ['nvr-brand', 'nvr-host', 'nvr-port', 'nvr-user', 'nvr-pass', 'nvr-channel', 'nvr-stream-type', 'playback-start', 'playback-end'].forEach(id => {
    document.getElementById(id).addEventListener('input', updatePreviewUrl);
  });

  async function updatePreviewUrl() {
    const payload = {
      brand: document.getElementById('nvr-brand').value,
      host: document.getElementById('nvr-host').value || '192.168.1.100',
      port: parseInt(document.getElementById('nvr-port').value) || 554,
      username: document.getElementById('nvr-user').value,
      password: document.getElementById('nvr-pass').value,
      channel: parseInt(document.getElementById('nvr-channel').value) || 1,
      stream_type: document.getElementById('nvr-stream-type').value,
      mode: nvrMode.value,
      start_time: document.getElementById('playback-start').value || null,
      end_time: document.getElementById('playback-end').value || null,
    };

    try {
      const res = await fetch('/api/nvr/build-url', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      generatedUrlInput.value = data.rtsp_url;
    } catch (e) {}
  }

  updatePreviewUrl();

  nvrForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const rtspUrl = generatedUrlInput.value;
    if (!rtspUrl) return;

    try {
      const res = await fetch('/api/stream/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source: rtspUrl,
          source_type: nvrMode.value === 'playback' ? 'nvr_playback' : 'rtsp',
          session_name: `NVR ${document.getElementById('nvr-brand').value} Ch${document.getElementById('nvr-channel').value}`
        })
      });
      if (res.ok) {
        showToast('Connecting to NVR stream...');
        document.querySelector('[data-tab="live-tab"]').click();
      }
    } catch (err) {
      alert('Failed to connect to NVR stream: ' + err);
    }
  });

  // Direct URL Button
  document.getElementById('btn-start-direct').addEventListener('click', async () => {
    const url = document.getElementById('direct-stream-url').value.trim();
    if (!url) return;
    await fetch('/api/stream/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        source: url,
        source_type: url === 'demo' ? 'demo' : 'rtsp',
        session_name: url === 'demo' ? 'Demo Simulation' : 'Direct RTSP Stream'
      })
    });
    showToast('Direct stream connected.');
    document.querySelector('[data-tab="live-tab"]').click();
  });
}

// 7. Video Upload Handler
function initVideoUpload() {
  const dropzone = document.getElementById('upload-zone');
  const fileInput = document.getElementById('video-file-input');
  const progressText = document.getElementById('upload-progress');

  ['dragenter', 'dragover'].forEach(name => {
    dropzone.addEventListener(name, (e) => {
      e.preventDefault();
      dropzone.classList.add('dragover');
    });
  });

  ['dragleave', 'drop'].forEach(name => {
    dropzone.addEventListener(name, (e) => {
      e.preventDefault();
      dropzone.classList.remove('dragover');
    });
  });

  dropzone.addEventListener('drop', (e) => {
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      uploadFile(e.dataTransfer.files[0]);
    }
  });

  fileInput.addEventListener('change', () => {
    if (fileInput.files.length > 0) {
      uploadFile(fileInput.files[0]);
    }
  });

  async function uploadFile(file) {
    const formData = new FormData();
    formData.append('file', file);
    progressText.style.display = 'block';

    try {
      const res = await fetch('/api/upload-video', {
        method: 'POST',
        body: formData
      });
      if (res.ok) {
        progressText.style.display = 'none';
        showToast('Video uploaded! Starting AI bag counting...');
        document.querySelector('[data-tab="live-tab"]').click();
      } else {
        throw new Error('Upload failed');
      }
    } catch (err) {
      progressText.style.display = 'none';
      alert('Upload error: ' + err);
    }
  }
}

// 8. Reports & Analytics
async function loadReports() {
  const startDate = document.getElementById('filter-start-date').value;
  const endDate = document.getElementById('filter-end-date').value;
  let url = '/api/reports';
  const params = [];
  if (startDate) params.push(`start_date=${startDate}`);
  if (endDate) params.push(`end_date=${endDate}`);
  if (params.length > 0) url += '?' + params.join('&');

  const tbody = document.getElementById('reports-table-body');
  try {
    const res = await fetch(url);
    const data = await res.json();
    if (!data.events || data.events.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--text-muted);">No bag crossing events found for selected period.</td></tr>';
      return;
    }

    tbody.innerHTML = data.events.map(ev => `
      <tr>
        <td>#${ev.id}</td>
        <td>${ev.timestamp}</td>
        <td>
          <span class="event-badge ${ev.direction.toLowerCase()}">${ev.direction}</span>
        </td>
        <td>Track #${ev.track_id}</td>
        <td>${Math.round(ev.confidence * 100)}%</td>
        <td>
          ${ev.snapshot_path ? `
            <img class="event-thumb" src="${ev.snapshot_path}" onclick="openModal('${ev.snapshot_path}', '${ev.direction}', '${ev.track_id}', '${ev.timestamp}')" alt="Snapshot" />
          ` : '<span style="color: var(--text-muted);">-</span>'}
        </td>
        <td style="color: var(--text-secondary);">${ev.notes || ''}</td>
      </tr>
    `).join('');
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--accent-out);">Error loading reports: ${e}</td></tr>`;
  }
}

function initReports() {
  const filterBtn = document.getElementById('btn-filter-reports');
  if (filterBtn) filterBtn.addEventListener('click', loadReports);

  const clearReportsBtn = document.getElementById('btn-clear-reports');
  if (clearReportsBtn) {
    clearReportsBtn.addEventListener('click', async () => {
      if (confirm('Are you sure you want to delete all bag crossing records and reset counts to 0? (সকল অডিট লগ ও কাউন্টার ডিলিট করতে চান?)')) {
        try {
          const res = await fetch('/api/stream/reset-counter', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ clear_database: true })
          });
          if (res.ok) {
            updateHUDCounters(0, 0, 0);
            const list = document.getElementById('event-feed-list');
            if (list) {
              list.innerHTML = '<div style="text-align: center; color: var(--text-muted); padding: 2rem;">Waiting for bag crossing events...</div>';
            }
            await loadReports();
            showToast('All records and counters reset to 0! (সকল রেকর্ড রিসেট হয়েছে)');
          } else {
            showToast('Reset failed.');
          }
        } catch (err) {
          alert('Error resetting data: ' + err);
        }
      }
    });
  }
}

// 9. Snapshot Verification Modal
function initModal() {
  const modal = document.getElementById('snapshot-modal');
  const closeBtn = document.getElementById('modal-close-btn');

  closeBtn.addEventListener('click', () => { modal.style.display = 'none'; });
  modal.addEventListener('click', (e) => {
    if (e.target === modal) modal.style.display = 'none';
  });
}

window.openModal = function(src, direction, trackId, timestamp) {
  const modal = document.getElementById('snapshot-modal');
  document.getElementById('modal-img').src = src;
  document.getElementById('modal-title').textContent = `Bag Crossing Audit: ${direction} (Track #${trackId})`;
  document.getElementById('modal-meta').textContent = `Recorded at ${timestamp} • High Resolution Tripwire Detection Frame`;
  modal.style.display = 'flex';
};

// Toast notification helper
function showToast(msg) {
  const toast = document.createElement('div');
  toast.style.position = 'fixed';
  toast.style.bottom = '24px';
  toast.style.right = '24px';
  toast.style.background = 'rgba(10, 13, 20, 0.9)';
  toast.style.backdropFilter = 'blur(12px)';
  toast.style.border = '1px solid var(--accent-cyan)';
  toast.style.color = '#fff';
  toast.style.padding = '12px 20px';
  toast.style.borderRadius = '10px';
  toast.style.boxShadow = '0 10px 30px rgba(0, 240, 255, 0.2)';
  toast.style.zIndex = '9999';
  toast.style.fontSize = '0.9rem';
  toast.style.fontWeight = '500';
  toast.textContent = msg;
  document.body.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transition = 'opacity 0.4s ease';
    setTimeout(() => toast.remove(), 400);
  }, 2500);
}

async function initModelSelector() {
  const modelSelect = document.getElementById('ai-model-select');
  if (!modelSelect) return;

  try {
    const res = await fetch('/api/models');
    if (res.ok) {
      const data = await res.json();
      if (data.current_model) {
        modelSelect.value = data.current_model;
      }
    }
  } catch (e) {}

  modelSelect.addEventListener('change', async () => {
    const chosen = modelSelect.value;
    showToast(`⏳ লোড হচ্ছে AI মডেল: ${chosen}...`);
    try {
      const res = await fetch('/api/models/select', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model_name: chosen })
      });
      const data = await res.json();
      if (res.ok) {
        showToast(`✅ ${data.message || 'AI মডেল সফলভাবে পরিবর্তন হয়েছে'}`);
      } else {
        showToast(`❌ মডেল পরিবর্তন ব্যর্থ: ${data.detail || 'Error'}`);
      }
    } catch (err) {
      showToast('❌ মডেল রিকোয়েস্টে সমস্যা হয়েছে');
    }
  });
}
