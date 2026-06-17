// ─── Game Core ──────────────────────────────────────────────────────────────

const CHAT_URL = '/api/chat';
const IMAGE_URL = '/api/image';
const GENERATE_URL = '/api/generate-game';
const START_URL = '/api/start-game';
const PRESETS_URL = '/api/presets';
const SAVE_URL = '/api/save';
const LOAD_API = '/api/load/';
const SAVES_LIST_URL = '/api/saves';

let audioCtx = null;
let typeGain = null;
let bgmGain = null;
let bgmTimer = null;
let bgmStep = 0;
let bgmDrones = [];
let audioEnabled = false;
let typeSoundCounter = 0;
let currentBlueprint = null;
let selectedIdentity = '';
let history = [];
let typingTimer = null;
let gameEnded = false;
let generatedScenes = [];
let currentSceneId = '';
let gameStarted = false;
const gameProgress = {
  turns: 0,
  main: new Set(),
  side: new Set(),
  locations: new Set(),
  scenes: new Set(),
  actions: []
};

// ─── Audio ──────────────────────────────────────────────────────────────────

function initAudio() {
  if (audioCtx) return;
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass) return;
  audioCtx = new AudioContextClass();
  typeGain = audioCtx.createGain();
  typeGain.gain.value = 0.08;
  typeGain.connect(audioCtx.destination);
  bgmGain = audioCtx.createGain();
  bgmGain.gain.value = 0.0001;
  bgmGain.connect(audioCtx.destination);
}

async function resumeAudio() {
  initAudio();
  if (audioCtx && audioCtx.state === 'suspended') await audioCtx.resume();
}

function playTone(freq, start, duration) {
  if (!audioCtx || !typeGain) return;
  const osc = audioCtx.createOscillator();
  const gain = audioCtx.createGain();
  osc.type = 'square';
  osc.frequency.setValueAtTime(freq, start);
  gain.gain.setValueAtTime(0.0001, start);
  gain.gain.exponentialRampToValueAtTime(0.055, start + 0.002);
  gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);
  osc.connect(gain);
  gain.connect(typeGain);
  osc.start(start);
  osc.stop(start + duration + 0.02);
}

function scheduleBgmNote(freq, start, duration, volume = 0.028) {
  if (!audioCtx || !bgmGain) return;
  const osc = audioCtx.createOscillator();
  const gain = audioCtx.createGain();
  osc.type = 'sine';
  osc.frequency.setValueAtTime(freq, start);
  gain.gain.setValueAtTime(0.0001, start);
  gain.gain.exponentialRampToValueAtTime(volume, start + 0.18);
  gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);
  osc.connect(gain);
  gain.connect(bgmGain);
  osc.start(start);
  osc.stop(start + duration + 0.1);
}

function startBgm() {
  if (!audioCtx || !bgmGain || bgmTimer) return;
  const now = audioCtx.currentTime;
  bgmGain.gain.cancelScheduledValues(now);
  bgmGain.gain.setValueAtTime(Math.max(bgmGain.gain.value, 0.0001), now);
  bgmGain.gain.linearRampToValueAtTime(0.42, now + 1.5);

  const dronePlan = [
    { freq: 110.00, type: 'sine', gain: 0.015 },
    { freq: 164.81, type: 'triangle', gain: 0.008 }
  ];
  bgmDrones = dronePlan.map(plan => {
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.type = plan.type;
    osc.frequency.setValueAtTime(plan.freq, now);
    gain.gain.setValueAtTime(0.0001, now);
    gain.gain.linearRampToValueAtTime(plan.gain, now + 2);
    osc.connect(gain);
    gain.connect(bgmGain);
    osc.start(now);
    return { osc, gain };
  });

  const scale = [220.00, 246.94, 277.18, 329.63, 369.99, 440.00, 554.37, 659.25];
  const pattern = [0, 2, 4, 5, 4, 2, 1, 2, 4, 6, 5, 4, 2, 0, 1, 2];
  const playPhrase = () => {
    if (!audioEnabled || !audioCtx) return;
    const base = audioCtx.currentTime + 0.04;
    for (let i = 0; i < 4; i += 1) {
      const noteIndex = pattern[(bgmStep + i) % pattern.length];
      scheduleBgmNote(scale[noteIndex], base + i * 0.72, 1.8, i === 0 ? 0.018 : 0.013);
    }
    bgmStep = (bgmStep + 4) % pattern.length;
  };
  playPhrase();
  bgmTimer = setInterval(playPhrase, 2850);
}

function stopBgm() {
  if (bgmTimer) clearInterval(bgmTimer);
  bgmTimer = null;
  if (!audioCtx || !bgmGain) return;
  const now = audioCtx.currentTime;
  bgmGain.gain.cancelScheduledValues(now);
  bgmGain.gain.setValueAtTime(Math.max(bgmGain.gain.value, 0.0001), now);
  bgmGain.gain.linearRampToValueAtTime(0.0001, now + 0.6);
  bgmDrones.forEach(({ osc, gain }) => {
    try {
      gain.gain.cancelScheduledValues(now);
      gain.gain.setValueAtTime(Math.max(gain.gain.value, 0.0001), now);
      gain.gain.linearRampToValueAtTime(0.0001, now + 0.6);
      osc.stop(now + 0.75);
    } catch (_) {}
  });
  bgmDrones = [];
}

async function toggleAudio() {
  audioEnabled = !audioEnabled;
  const btn = document.getElementById('audio-toggle');
  if (audioEnabled) {
    btn.classList.add('active');
    btn.textContent = '静音';
    btn.setAttribute('aria-pressed', 'true');
    await resumeAudio();
    startBgm();
  } else {
    btn.classList.remove('active');
    btn.textContent = '音乐';
    btn.setAttribute('aria-pressed', 'false');
    stopBgm();
  }
}

function playTypingSound(char) {
  if (!audioEnabled || !audioCtx || !typeGain || !char.trim()) return;
  typeSoundCounter += 1;
  if (typeSoundCounter % 2 !== 0) return;
  playTone(860 + Math.random() * 260, audioCtx.currentTime, 0.018);
}

// ─── UI Helpers ─────────────────────────────────────────────────────────────

function updateStatus(text) {
  const status = document.getElementById('status');
  status.innerHTML = '';
  const parts = String(text || '').replace(/[|｜]/g, '|').split('|').filter(Boolean);
  parts.slice(0, 6).forEach(part => {
    const span = document.createElement('span');
    span.textContent = part.trim();
    status.appendChild(span);
  });
}

function setBusy(isBusy, text = '生成中') {
  const btn = document.getElementById('generate-game');
  btn.disabled = isBusy;
  document.getElementById('generate-hint').innerHTML = isBusy ?
    `<span class="loading">▌</span> ${text}` :
    '先生成世界蓝图，再选择身份开局。';
}

async function postJSON(url, payload) {
  const resp = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.message || data.error?.message || '请求失败');
  return data;
}

function escapeHTML(text) {
  return String(text ?? '').replace(/[&<>"']/g, ch => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
  }[ch]));
}

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function showToast(msg) {
  let toast = document.getElementById('toast');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'toast';
    toast.className = 'toast';
    document.body.appendChild(toast);
  }
  toast.textContent = msg;
  toast.classList.add('show');
  clearTimeout(toast._hide);
  toast._hide = setTimeout(() => toast.classList.remove('show'), 2500);
}

// ─── Presets & Setup ────────────────────────────────────────────────────────

let presets = [];

async function loadPresets() {
  try {
    const resp = await fetch(PRESETS_URL);
    const data = await resp.json();
    presets = data.presets || [];
    const container = document.getElementById('presets-container');
    if (!container) return;
    container.innerHTML = '';
    presets.forEach((p, idx) => {
      const card = document.createElement('div');
      card.className = 'preset-card' + (idx === 0 ? ' selected' : '');
      card.dataset.id = p.id;
      card.innerHTML = `
        <strong>${escapeHTML(p.title)}</strong>
        <p>${escapeHTML(p.description)}</p>
        ${p.sourceUrl ? `<a class="source-link" href="${escapeHTML(p.sourceUrl)}" target="_blank" rel="noopener noreferrer">来源：维基文库《西游记》</a>` : ''}
        <span class="check">✓</span>
      `;
      card.addEventListener('click', () => selectPreset(p.id));
      container.appendChild(card);
    });
  } catch (e) {
    // fallback — single preset
  }
}

function selectPreset(id) {
  document.querySelectorAll('.preset-card').forEach(c => c.classList.remove('selected'));
  const card = document.querySelector(`.preset-card[data-id="${id}"]`);
  if (card) card.classList.add('selected');
}

function getSelectedPresetId() {
  const sel = document.querySelector('.preset-card.selected');
  return sel ? sel.dataset.id : 'xiyouji';
}

function getPresetSource(id) {
  // The server has the full source text; we just pass the id
  return null;
}

// ─── Generate Game ──────────────────────────────────────────────────────────

async function generateGame() {
  await resumeAudio();

  const presetId = getSelectedPresetId();
  const sourceText = document.getElementById('story-input').value.trim();

  setBusy(true, 'AI 正在生成世界蓝图…');

  try {
    const data = await postJSON(GENERATE_URL, {
      sourceTitle: presets.find(p => p.id === presetId)?.title || '西游记古文版',
      sourceText: sourceText,
      presetId: presetId,
    });

    currentBlueprint = data.blueprint;
    document.getElementById('setup-panel').classList.add('hidden');
    document.getElementById('identity-panel').classList.remove('hidden');
    document.getElementById('blueprint-summary').innerHTML = summarizeBlueprint(currentBlueprint);
    renderIdentityOptions(currentBlueprint.identitySuggestions);
    document.getElementById('custom-identity').value = '';
    selectedIdentity = '';
    document.getElementById('status').innerHTML = '<span>📚 蓝图中</span><span>📋 选择身份</span>';
    showToast('世界蓝图已生成');
  } catch (e) {
    showToast('生成失败: ' + e.message);
  } finally {
    setBusy(false);
  }
}

function summarizeBlueprint(blueprint) {
  const factions = asArray(blueprint.factions).slice(0, 4).map(item => escapeHTML(item.name || item)).join(' / ');
  const locations = asArray(blueprint.locations).slice(0, 5).map(item => escapeHTML(item.name || item)).join(' / ');
  return `
    <p><strong>${escapeHTML(blueprint.title || '未命名文字游戏')}</strong></p>
    <p>${escapeHTML(blueprint.worldSummary || '')}</p>
    <p class="muted">势力：${factions || '待生成'}<br>地点：${locations || '待生成'}</p>
  `;
}

function renderIdentityOptions(identities) {
  const list = document.getElementById('identity-list');
  list.innerHTML = '';
  asArray(identities).slice(0, 5).forEach((identity, index) => {
    const name = identity.name || identity;
    const desc = identity.description || '';
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'identity-btn' + (index === 0 ? ' active' : '');
    btn.innerHTML = `<strong>${escapeHTML(name)}</strong>${desc ? `<small>${escapeHTML(desc)}</small>` : ''}`;
    btn.dataset.identity = name;
    btn.addEventListener('click', () => selectIdentity(name, btn));
    list.appendChild(btn);
  });
  // Select first by default
  const first = list.querySelector('.identity-btn');
  if (first) selectIdentity(presets[0]?.title ? '' : '', first);
}

function selectIdentity(name, btn) {
  selectedIdentity = name;
  document.querySelectorAll('.identity-btn').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
}

// ─── Start Game ─────────────────────────────────────────────────────────────

async function startGame() {
  const identity = selectedIdentity || document.getElementById('custom-identity').value.trim() || '无名旅人';
  document.getElementById('generate-game').disabled = true;
  document.getElementById('start-game').disabled = true;
  document.getElementById('start-game').textContent = '开局中…';

  try {
    const data = await postJSON(START_URL, {
      blueprint: currentBlueprint,
      identity: identity,
    });

    const opening = data.opening;
    gameStarted = true;
    gameEnded = false;
    history = [];
    gameProgress.turns = 0;
    gameProgress.main = new Set();
    gameProgress.side = new Set();
    gameProgress.locations = new Set();
    gameProgress.scenes = new Set();
    gameProgress.actions = [];

    // Switch to game UI
    document.getElementById('identity-panel').classList.add('hidden');
    document.getElementById('setup-panel').classList.add('hidden');
    document.getElementById('input-area').classList.remove('hidden');
    document.getElementById('opts-area').style.display = 'flex';
    document.getElementById('end-run').classList.remove('hidden');
    document.getElementById('save-game').classList.remove('hidden');

    const output = document.getElementById('output');
    output.innerHTML = '';

    appendGMMessage(opening);
    maybeGenerateImage(opening);
    showToast('游戏开始');
  } catch (e) {
    showToast('开局失败: ' + e.message);
  } finally {
    document.getElementById('generate-game').disabled = false;
    document.getElementById('start-game').disabled = false;
    document.getElementById('start-game').textContent = '以此身份开局';
  }
}

// ─── Chat & Gameplay ────────────────────────────────────────────────────────

async function sendMessage() {
  const input = document.getElementById('input');
  const msg = input.value.trim();
  if (!msg || gameEnded) return;

  input.value = '';
  appendMessage('player', msg);
  history.push({ role: 'user', content: msg });
  gameProgress.turns += 1;
  gameProgress.actions.push(msg);

  document.getElementById('send').disabled = true;
  document.getElementById('opts-area').innerHTML = '';

  try {
    const data = await postJSON(CHAT_URL, {
      messages: history,
      blueprint: currentBlueprint,
      progress: {
        turns: gameProgress.turns,
        main: [...gameProgress.main],
        side: [...gameProgress.side],
        locations: [...gameProgress.locations],
        actions: gameProgress.actions
      }
    });

    let content;
    if (data.choices && data.choices[0]) {
      content = data.choices[0].message?.content || data.choices[0].text || '（主持人沉默不语）';
    } else {
      content = data.content || data.opening || '（主持人沉默了）';
    }

    history.push({ role: 'assistant', content: content });
    appendGMMessage(content);
    maybeGenerateImage(content);
    parseOptions(content);
  } catch (e) {
    appendGMMessage('（主持人走神了——网络异常）');
    showToast('发送失败: ' + e.message);
  } finally {
    document.getElementById('send').disabled = false;
    input.focus();
  }
}

function parseOptions(text) {
  const lines = text.split('\n').filter(l => l.trim());
  const optionPattern = /^[A-Da-d][.、．]\s*(.+)$/;
  const opts = lines.filter(l => optionPattern.test(l.trim())).slice(-4);
  const area = document.getElementById('opts-area');
  area.innerHTML = '';
  if (opts.length === 0) return;
  opts.forEach(optText => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn-opt';
    btn.textContent = optText.trim();
    btn.addEventListener('click', () => {
      document.getElementById('input').value = optText.replace(/^[A-Da-d][.、．]\s*/, '').trim();
      sendMessage();
    });
    area.appendChild(btn);
  });
}

function maybeGenerateImage(text) {
  if (!text) return;
  const sceneMatch = text.match(/📍\s*(.+?)\s*[|｜]/);
  const sceneLabel = sceneMatch ? sceneMatch[1].trim() : '';
  if (!sceneLabel || sceneLabel === '等待故事' || generatedScenes.includes(sceneLabel)) return;

  // Find matching scene prompt from blueprint
  let scenePrompt = '';
  if (currentBlueprint?.scenes) {
    for (const s of currentBlueprint.scenes) {
      const keywords = s.keywords || [];
      if (keywords.some(k => sceneLabel.includes(k)) || sceneLabel.includes(s.label)) {
        scenePrompt = s.prompt || s.label;
        break;
      }
    }
  }
  if (!scenePrompt) scenePrompt = sceneLabel;

  generatedScenes.push(sceneLabel);

  fetch(IMAGE_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scene: scenePrompt, label: sceneLabel })
  })
  .then(r => r.json())
  .then(data => {
    if (data.url) {
      const container = document.getElementById('output');
      const imgDiv = document.createElement('div');
      imgDiv.className = 'msg-image';
      const img = document.createElement('img');
      img.src = data.url;
      img.alt = sceneLabel;
      img.loading = 'lazy';
      imgDiv.appendChild(img);
      container.appendChild(imgDiv);
      container.scrollTop = container.scrollHeight;
      // set scene background
      document.documentElement.style.setProperty('--scene-bg', `url(${data.url})`);
    }
  })
  .catch(() => {});
}

function appendGMMessage(text) {
  const output = document.getElementById('output');
  const div = document.createElement('div');
  div.className = 'msg gm';

  // Typewriter effect
  let idx = 0;
  let htmlBuffer = '';
  const chars = text.split('');
  const step = () => {
    if (idx < chars.length && gameStarted) {
      const chunk = chars.slice(idx, idx + 3).join('');
      htmlBuffer += escapeHTML(chunk);
      div.innerHTML = htmlBuffer.replace(/\n/g, '<br>');
      for (const ch of chunk) playTypingSound(ch);
      idx += 3;
      typingTimer = setTimeout(step, 18);
    } else {
      // Final render
      div.textContent = '';
      div.innerHTML = escapeHTML(text).replace(/\n/g, '<br>');
      updateStatus(text);
    }
  };
  step();

  output.appendChild(div);
  output.scrollTop = output.scrollHeight;
}

function appendMessage(role, text) {
  const output = document.getElementById('output');
  const div = document.createElement('div');
  div.className = `msg ${role}`;
  div.innerHTML = escapeHTML(text).replace(/\n/g, '<br>');
  output.appendChild(div);
  output.scrollTop = output.scrollHeight;
}

// ─── Save / Load ────────────────────────────────────────────────────────────

async function saveGame() {
  if (!gameStarted || gameEnded) return;
  try {
    const data = await postJSON(SAVE_URL, {
      title: currentBlueprint?.title || 'AI 文字游戏存档',
      blueprint: currentBlueprint,
      identity: selectedIdentity,
      history: history,
      progress: {
        turns: gameProgress.turns,
        main: [...gameProgress.main],
        side: [...gameProgress.side],
        locations: [...gameProgress.locations],
        actions: gameProgress.actions,
        scenes: [...generatedScenes],
      },
      scene: currentSceneId,
    });
    showToast('存档成功 ✓ ID: ' + data.saveId);
  } catch (e) {
    showToast('存档失败: ' + e.message);
  }
}

function showSavesPanel() {
  const output = document.getElementById('output');
  const panel = document.createElement('div');
  panel.className = 'panel';
  panel.innerHTML = '<h2>存档列表</h2><div id="saves-list"><p class="loading">▌ 加载中…</p></div>';
  output.appendChild(panel);
  output.scrollTop = output.scrollHeight;

  fetch(SAVES_LIST_URL)
    .then(r => r.json())
    .then(data => {
      const list = document.getElementById('saves-list');
      if (!data.saves || data.saves.length === 0) {
        list.innerHTML = '<p class="muted">暂无存档</p>';
        return;
      }
      list.innerHTML = '';
      data.saves.reverse().forEach(s => {
        const card = document.createElement('div');
        card.className = 'save-card';
        const date = new Date(s.timestamp * 1000).toLocaleString('zh-CN');
        card.innerHTML = `<strong>${escapeHTML(s.title)}</strong><small>${date}</small>`;
        card.addEventListener('click', () => loadGame(s.id));
        list.appendChild(card);
      });
    })
    .catch(() => {
      const list = document.getElementById('saves-list');
      list.innerHTML = '<p class="muted">加载失败</p>';
    });
}

async function loadGame(saveId) {
  try {
    const resp = await fetch(LOAD_API + saveId);
    const data = await resp.json();
    if (data.save) {
      const s = data.save;
      currentBlueprint = s.blueprint;
      selectedIdentity = s.identity || '';
      history = s.history || [];
      generatedScenes = s.progress?.scenes || [];
      gameProgress.turns = s.progress?.turns || 0;
      gameProgress.main = new Set(s.progress?.main || []);
      gameProgress.side = new Set(s.progress?.side || []);
      gameProgress.locations = new Set(s.progress?.locations || []);
      gameProgress.actions = s.progress?.actions || [];
      gameStarted = true;
      gameEnded = false;

      document.getElementById('setup-panel').classList.add('hidden');
      document.getElementById('identity-panel').classList.add('hidden');
      document.getElementById('input-area').classList.remove('hidden');
      document.getElementById('opts-area').style.display = 'flex';
      document.getElementById('end-run').classList.remove('hidden');
      document.getElementById('save-game').classList.remove('hidden');

      const output = document.getElementById('output');
      output.innerHTML = '';

      // Replay history
      for (const msg of history) {
        if (msg.role === 'assistant') {
          appendGMMessage(msg.content);
        } else if (msg.role === 'user') {
          appendMessage('player', msg.content);
        }
      }

      // Parse last message options
      if (history.length > 0) {
        const last = history[history.length - 1];
        if (last.role === 'assistant') parseOptions(last.content);
      }

      showToast('读档成功');
    }
  } catch (e) {
    showToast('读档失败');
  }
}

// ─── End Game ───────────────────────────────────────────────────────────────

function endGame() {
  gameEnded = true;
  document.getElementById('input-area').classList.add('hidden');
  document.getElementById('opts-area').style.display = 'none';
  document.getElementById('end-run').classList.add('hidden');
  document.getElementById('save-game').classList.add('hidden');

  const output = document.getElementById('output');
  const summaryDiv = document.createElement('div');
  summaryDiv.className = 'msg system';
  summaryDiv.innerHTML = `旅程到此结束 · 共 ${gameProgress.turns} 回合`;
  output.appendChild(summaryDiv);

  // Show credits overlay
  const overlay = document.getElementById('credits-overlay');
  overlay.classList.add('active');

  const roll = document.getElementById('credits-roll');
  roll.innerHTML = `
    <h2>${escapeHTML(currentBlueprint?.title || 'AI 文字游戏')}</h2>
    <p>—— 你的冒险已落幕 ——</p>
    <div class="big-stat">${gameProgress.turns} 回合</div>
    <h3>探索区域</h3>
    <p>${[...gameProgress.locations].join(' · ') || '花果山'}</p>
    <h3>主线推进</h3>
    <p>${[...gameProgress.main].join(' · ') || '开局入劫'}</p>
    <h3>你所扮演的</h3>
    <p>${escapeHTML(selectedIdentity || '无名旅人')}</p>
  `;
}

function restartGame() {
  document.getElementById('credits-overlay').classList.remove('active');

  gameStarted = false;
  gameEnded = false;
  currentBlueprint = null;
  history = [];
  generatedScenes = [];
  document.getElementById('output').innerHTML = '';
  document.getElementById('opts-area').innerHTML = '';
  document.getElementById('opts-area').style.display = 'none';
  document.getElementById('input-area').classList.add('hidden');
  document.getElementById('save-game').classList.add('hidden');

  // Show setup again
  document.getElementById('setup-panel').classList.remove('hidden');
  document.getElementById('identity-panel').classList.add('hidden');
  document.getElementById('end-run').classList.add('hidden');
  document.getElementById('status').innerHTML = '<span>📚 等待故事</span><span>🧭 生成器待机</span><span>🎭 身份未定</span>';
}

// ─── DOM Content Loaded ─────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', async () => {
  // Load presets into dynamic container
  await loadPresets();

  // Bind events
  document.getElementById('audio-toggle').addEventListener('click', toggleAudio);
  document.getElementById('generate-game').addEventListener('click', generateGame);
  document.getElementById('start-game').addEventListener('click', startGame);
  document.getElementById('regenerate-game').addEventListener('click', generateGame);
  document.getElementById('send').addEventListener('click', sendMessage);
  document.getElementById('end-run').addEventListener('click', endGame);
  document.getElementById('continue-run').addEventListener('click', () => {
    document.getElementById('credits-overlay').classList.remove('active');
  });
  document.getElementById('restart-run').addEventListener('click', restartGame);

  // Save button
  const saveBtn = document.getElementById('save-game');
  if (saveBtn) saveBtn.addEventListener('click', saveGame);

  // Load saves button
  const loadBtn = document.getElementById('load-save');
  if (loadBtn) loadBtn.addEventListener('click', showSavesPanel);

  // Enter to send
  document.getElementById('input').addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  // Custom identity: deselect preset buttons when typing
  document.getElementById('custom-identity').addEventListener('input', function() {
    if (this.value.trim()) {
      document.querySelectorAll('.identity-btn').forEach(b => b.classList.remove('active'));
      selectedIdentity = this.value.trim();
    }
  });
});
