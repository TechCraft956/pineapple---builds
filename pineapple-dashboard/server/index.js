/**
 * Pineapple Dashboard — backend.
 *
 * Express server + a JSON-file state store. It serves the built React
 * frontend (client/dist) and exposes the same actions the live dashboard
 * uses, as REST endpoints under /api/actions/<name>.
 *
 * State lives in ./data/dashboard.json (created from
 * ./data/dashboard.sample.json on first run). That file is gitignored:
 * it holds the owner's live data and must never be committed.
 *
 *   npm run dev    — start on PORT (default 3001)
 *   npm start      — same, production mode
 */
const express = require('express');
const fs = require('fs');
const path = require('path');

const PORT = Number(process.env.PORT || 3001);
const DATA_DIR = path.join(__dirname, 'data');
const STATE_FILE = path.join(DATA_DIR, 'dashboard.json');
const SAMPLE_FILE = path.join(DATA_DIR, 'dashboard.sample.json');
const CLIENT_DIST = path.join(__dirname, '..', 'client', 'dist');

const app = express();
app.use(express.json({ limit: '1mb' }));

// ---------------------------------------------------------------- state ---

function emptyState() {
  return {
    lastUpdatedAt: new Date().toISOString(),
    accounts: [],
    needs: [],
    activity: [],
    sections: [],
  };
}

function loadState() {
  try {
    return JSON.parse(fs.readFileSync(STATE_FILE, 'utf8'));
  } catch (err) {
    if (err.code !== 'ENOENT') throw err;
    const sample = JSON.parse(fs.readFileSync(SAMPLE_FILE, 'utf8'));
    fs.mkdirSync(DATA_DIR, { recursive: true });
    fs.writeFileSync(STATE_FILE, JSON.stringify(sample, null, 2));
    return sample;
  }
}

function saveState(state) {
  state.lastUpdatedAt = new Date().toISOString();
  // Atomic-ish write: temp file + rename, so a crash mid-write cannot
  // corrupt the only copy of the state.
  const tmp = `${STATE_FILE}.tmp-${process.pid}`;
  fs.writeFileSync(tmp, JSON.stringify(state, null, 2));
  fs.renameSync(tmp, STATE_FILE);
  return state;
}

function nextId(state) {
  const ids = [
    ...state.activity.map((a) => a.id || 0),
    ...state.sections.flatMap((s) => s.items.map((i) => i.id || 0)),
    ...state.needs.map((n) => n.id || 0),
  ];
  return (ids.length ? Math.max(...ids) : 0) + 1;
}

function sectionOr404(state, key, res) {
  const section = state.sections.find((s) => s.key === key);
  if (!section) {
    res.status(404).json({ ok: false, error: `no section with key "${key}"` });
    return null;
  }
  return section;
}

// ---------------------------------------------------------------- routes ---

app.get('/api/health', (_req, res) => res.json({ ok: true, service: 'pineapple-dashboard' }));

// getdashboard — the whole dashboard state, exactly the live action's shape.
app.get('/api/dashboard', (_req, res) => {
  res.json({ ok: true, data: loadState() });
});

// addactivity — append one activity entry (newest first in the feed).
app.post('/api/actions/addactivity', (req, res) => {
  const { text } = req.body || {};
  if (!text || typeof text !== 'string') {
    return res.status(400).json({ ok: false, error: 'text is required' });
  }
  const state = loadState();
  const entry = { id: nextId(state), text, createdAt: new Date().toISOString() };
  state.activity.unshift(entry);
  res.json({ ok: true, data: saveState(state), activity: entry });
});

// addneed — add an item to the Needs list.
app.post('/api/actions/addneed', (req, res) => {
  const { label, detail } = req.body || {};
  if (!label || typeof label !== 'string') {
    return res.status(400).json({ ok: false, error: 'label is required' });
  }
  const state = loadState();
  const need = { id: nextId(state), label, detail: detail || '', createdAt: new Date().toISOString() };
  state.needs.push(need);
  res.json({ ok: true, data: saveState(state), need });
});

// removeneed — remove a need by id (or label).
app.post('/api/actions/removeneed', (req, res) => {
  const { id, label } = req.body || {};
  const state = loadState();
  const before = state.needs.length;
  state.needs = state.needs.filter((n) => n.id !== id && n.label !== label);
  if (state.needs.length === before) {
    return res.status(404).json({ ok: false, error: 'need not found' });
  }
  res.json({ ok: true, data: saveState(state) });
});

// updatesection — update a section's summary and/or status.
app.post('/api/actions/updatesection', (req, res) => {
  const { key, summary, status } = req.body || {};
  const state = loadState();
  const section = sectionOr404(state, key, res);
  if (!section) return;
  if (typeof summary === 'string') section.summary = summary;
  if (typeof status === 'string') section.status = status;
  section.updatedAt = new Date().toISOString();
  res.json({ ok: true, data: saveState(state), section });
});

// upsertitem — add a new item to a section, or update the item with the
// same itemKey / id. Items are the rows inside a section.
app.post('/api/actions/upsertitem', (req, res) => {
  const { sectionKey, item } = req.body || {};
  if (!sectionKey || !item || typeof item.label !== 'string') {
    return res.status(400).json({ ok: false, error: 'sectionKey and item.label are required' });
  }
  const state = loadState();
  const section = sectionOr404(state, sectionKey, res);
  if (!section) return;
  const existing = section.items.find(
    (i) => (item.itemKey && i.itemKey === item.itemKey) || (item.id && i.id === item.id),
  );
  let saved;
  if (existing) {
    Object.assign(existing, item);
    saved = existing;
  } else {
    saved = {
      id: item.id || nextId(state),
      itemKey: item.itemKey || `item-${Date.now()}`,
      label: item.label,
      detail: item.detail || '',
      sortOrder: item.sortOrder ?? section.items.length + 1,
      tag: item.tag ?? null,
    };
    section.items.push(saved);
  }
  section.items.sort((a, b) => (a.sortOrder || 0) - (b.sortOrder || 0));
  section.updatedAt = new Date().toISOString();
  res.json({ ok: true, data: saveState(state), item: saved });
});

// removeitem — remove an item from a section by id or itemKey.
app.post('/api/actions/removeitem', (req, res) => {
  const { sectionKey, id, itemKey } = req.body || {};
  const state = loadState();
  const section = sectionOr404(state, sectionKey, res);
  if (!section) return;
  const before = section.items.length;
  section.items = section.items.filter((i) => i.id !== id && i.itemKey !== itemKey);
  if (section.items.length === before) {
    return res.status(404).json({ ok: false, error: 'item not found' });
  }
  section.updatedAt = new Date().toISOString();
  res.json({ ok: true, data: saveState(state) });
});

// setaccountbalance — set an account's balance (creates the account if the
// key is new). Balances are stored in cents; balanceLabel is the display
// string (e.g. "~$82").
app.post('/api/actions/setaccountbalance', (req, res) => {
  const { key, name, balanceCents, balanceLabel, note } = req.body || {};
  if (!key || typeof balanceCents !== 'number') {
    return res.status(400).json({ ok: false, error: 'key and numeric balanceCents are required' });
  }
  const state = loadState();
  let account = state.accounts.find((a) => a.key === key);
  if (!account) {
    account = { key, name: name || key, balanceCents, balanceLabel: balanceLabel || '', note: note || '', updatedAt: new Date().toISOString() };
    state.accounts.push(account);
  } else {
    account.balanceCents = balanceCents;
    if (typeof balanceLabel === 'string') account.balanceLabel = balanceLabel;
    if (typeof note === 'string') account.note = note;
    if (typeof name === 'string') account.name = name;
    account.updatedAt = new Date().toISOString();
  }
  res.json({ ok: true, data: saveState(state), account });
});

// refreshdashboard — record a refresh pass (bumps lastUpdatedAt; callers
// may include a short note that lands in the activity feed).
app.post('/api/actions/refreshdashboard', (req, res) => {
  const { note } = req.body || {};
  const state = loadState();
  if (note) {
    state.activity.unshift({ id: nextId(state), text: note, createdAt: new Date().toISOString() });
  }
  res.json({ ok: true, data: saveState(state) });
});

// applyrefresh — append a batch of activity entries from a refresh run.
app.post('/api/actions/applyrefresh', (req, res) => {
  const { activity } = req.body || {};
  if (!Array.isArray(activity)) {
    return res.status(400).json({ ok: false, error: 'activity must be an array of {text} entries' });
  }
  const state = loadState();
  const added = activity.map((a) => ({
    id: nextId(state),
    text: a.text,
    createdAt: a.createdAt || new Date().toISOString(),
  }));
  state.activity.unshift(...added);
  res.json({ ok: true, data: saveState(state), added });
});

// seeddashboard — reset state to the sample seed. Refuses unless
// {force:true} is passed, so a stray call cannot wipe live data.
app.post('/api/actions/seeddashboard', (req, res) => {
  const { force } = req.body || {};
  if (force !== true) {
    return res.status(400).json({ ok: false, error: 'pass {force:true} to reset state to the sample seed' });
  }
  const sample = JSON.parse(fs.readFileSync(SAMPLE_FILE, 'utf8'));
  fs.writeFileSync(STATE_FILE, JSON.stringify(sample, null, 2));
  res.json({ ok: true, data: loadState() });
});

// ------------------------------------------------------- static frontend ---

if (fs.existsSync(CLIENT_DIST)) {
  app.use(express.static(CLIENT_DIST));
  // SPA fallback: anything that is not /api/* serves the app.
  app.get('*', (req, res, next) => {
    if (req.path.startsWith('/api/')) return next();
    res.sendFile(path.join(CLIENT_DIST, 'index.html'));
  });
} else {
  app.get('/', (_req, res) => {
    res
      .status(200)
      .send('Pineapple Dashboard API is running. Build the client first: npm run build. API: GET /api/dashboard');
  });
}

app.listen(PORT, () => {
  // eslint-disable-next-line no-console
  console.log(`Pineapple Dashboard listening on http://localhost:${PORT}`);
  // eslint-disable-next-line no-console
  console.log(`State file: ${STATE_FILE}`);
});
