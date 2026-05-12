// ── Utility ────────────────────────────────────────────────────────────────

function bufferToBase64url(buffer) {
  const bytes = new Uint8Array(buffer);
  let str = '';
  for (const b of bytes) str += String.fromCharCode(b);
  return btoa(str).replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');
}

function base64urlToBuffer(b64url) {
  const b64 = b64url.replace(/-/g, '+').replace(/_/g, '/');
  const str = atob(b64);
  const buf = new ArrayBuffer(str.length);
  const bytes = new Uint8Array(buf);
  for (let i = 0; i < str.length; i++) bytes[i] = str.charCodeAt(i);
  return buf;
}

function fmtUsd(n) {
  if (!n) return '—';
  if (n >= 1e9) return '$' + (n / 1e9).toFixed(1) + 'B';
  if (n >= 1e6) return '$' + (n / 1e6).toFixed(1) + 'M';
  if (n >= 1e3) return '$' + (n / 1e3).toFixed(0) + 'K';
  return '$' + n.toFixed(0);
}

function el(id) { return document.getElementById(id); }

// ── Auth ───────────────────────────────────────────────────────────────────

async function checkAuth() {
  const resp = await fetch('/api/auth/status');
  const { registered, authenticated } = await resp.json();
  if (authenticated) {
    showDashboard();
  } else if (registered) {
    el('login-box').style.display = 'block';
  } else {
    el('register-box').style.display = 'block';
  }
}

async function registerPasskey() {
  el('register-error').textContent = '';
  try {
    const beginResp = await fetch('/api/auth/register/begin', { method: 'POST' });
    if (!beginResp.ok) { el('register-error').textContent = await beginResp.text(); return; }
    const options = await beginResp.json();
    options.challenge = base64urlToBuffer(options.challenge);
    options.user.id = base64urlToBuffer(options.user.id);
    if (options.excludeCredentials) {
      options.excludeCredentials = options.excludeCredentials.map(c => ({ ...c, id: base64urlToBuffer(c.id) }));
    }
    const credential = await navigator.credentials.create({ publicKey: options });
    const body = {
      id: credential.id,
      rawId: bufferToBase64url(credential.rawId),
      type: credential.type,
      response: {
        clientDataJSON: bufferToBase64url(credential.response.clientDataJSON),
        attestationObject: bufferToBase64url(credential.response.attestationObject),
      },
    };
    const finishResp = await fetch('/api/auth/register/finish', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (finishResp.ok) { window.location.reload(); }
    else { el('register-error').textContent = 'Registration failed. Try again.'; }
  } catch (e) {
    el('register-error').textContent = e.message || 'Registration failed.';
  }
}

async function loginPasskey() {
  el('login-error').textContent = '';
  try {
    const beginResp = await fetch('/api/auth/login/begin', { method: 'POST' });
    if (!beginResp.ok) { el('login-error').textContent = await beginResp.text(); return; }
    const options = await beginResp.json();
    options.challenge = base64urlToBuffer(options.challenge);
    if (options.allowCredentials) {
      options.allowCredentials = options.allowCredentials.map(c => ({ ...c, id: base64urlToBuffer(c.id) }));
    }
    const credential = await navigator.credentials.get({ publicKey: options });
    const body = {
      id: credential.id,
      rawId: bufferToBase64url(credential.rawId),
      type: credential.type,
      response: {
        clientDataJSON: bufferToBase64url(credential.response.clientDataJSON),
        authenticatorData: bufferToBase64url(credential.response.authenticatorData),
        signature: bufferToBase64url(credential.response.signature),
        userHandle: credential.response.userHandle ? bufferToBase64url(credential.response.userHandle) : null,
      },
    };
    const finishResp = await fetch('/api/auth/login/finish', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (finishResp.ok) { window.location.reload(); }
    else { el('login-error').textContent = 'Login failed. Try again.'; }
  } catch (e) {
    el('login-error').textContent = e.message || 'Login failed.';
  }
}

async function logout() {
  await fetch('/api/auth/logout', { method: 'POST' });
  window.location.reload();
}

// ── Dashboard ──────────────────────────────────────────────────────────────

function showDashboard() {
  el('auth-screen').style.display = 'none';
  el('dashboard').style.display = 'block';
  refreshAll();
  setInterval(refreshAll, 30000);
}

async function refreshAll() {
  await Promise.all([
    refreshSignals(),
    refreshSources(),
    refreshRotation(),
    refreshWatchlist(),
    refreshCatalysts(),
    refreshBasket(),
    refreshOptions(),
  ]);
  el('last-updated').textContent = 'updated ' + new Date().toLocaleTimeString();
}

async function refreshSignals() {
  const resp = await fetch('/api/signals?hours=24');
  if (!resp.ok) return;
  const { signals, total } = await resp.json();
  el('signal-count').textContent = `(${total})`;
  const tbody = el('signal-tbody');
  tbody.innerHTML = signals.map(s => `
    <tr>
      <td>${s.published}</td>
      <td class="source">${s.source}</td>
      <td class="source">${s.signal_type}</td>
      <td class="ticker">${s.ticker || '—'}</td>
      <td style="max-width:300px;overflow:hidden;text-overflow:ellipsis">${s.title}</td>
      <td class="amount">${fmtUsd(s.amount_usd)}</td>
    </tr>
  `).join('') || '<tr><td colspan="6" style="color:var(--muted);text-align:center">No signals. Run govspend ingest.</td></tr>';
}

async function refreshSources() {
  const resp = await fetch('/api/sources');
  if (!resp.ok) return;
  const { sources } = await resp.json();
  const maxCount = Math.max(...Object.values(sources), 1);
  const emojis = {
    edgar:'📋', usaspending:'💰', fedregister:'📜', congress:'🏛️',
    sbir:'🔬', norway:'🇳🇴', catalyst:'📅', grants_gov:'🏆',
    propublica:'⚖️', lobbying:'💼',
  };
  el('sources-body').innerHTML = Object.entries(sources).map(([src, count]) => `
    <div class="bar-row">
      <div class="bar-label">${emojis[src] || ''} ${src}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${count / maxCount * 100}%"></div></div>
      <div class="bar-count">${count}</div>
    </div>
  `).join('');
}

async function refreshRotation() {
  const resp = await fetch('/api/sector-rotation');
  if (!resp.ok) return;
  const { sectors } = await resp.json();
  el('rotation-tbody').innerHTML = sectors.map(s => {
    const pct = s.pct_change;
    const cls = pct === null ? 'flat' : pct > 0 ? 'up' : pct < 0 ? 'down' : 'flat';
    const pctStr = pct === null ? 'new' : (pct >= 0 ? '+' : '') + pct.toFixed(0) + '%';
    return `<tr>
      <td>${s.sector}</td>
      <td>${s.current_count}</td>
      <td style="color:var(--muted)">${s.prior_count}</td>
      <td class="${cls}">${pctStr}</td>
    </tr>`;
  }).join('') || '<tr><td colspan="4" style="color:var(--muted)">No data</td></tr>';
}

async function refreshWatchlist() {
  const resp = await fetch('/api/watchlist?hours=24');
  if (!resp.ok) return;
  const { tickers } = await resp.json();
  el('watchlist-tbody').innerHTML = tickers.map(t => `
    <tr>
      <td class="ticker">${t.ticker}</td>
      <td>${t.signal_count}</td>
      <td class="amount">${fmtUsd(t.total_contract_usd)}</td>
    </tr>
  `).join('') || '<tr><td colspan="3" style="color:var(--muted)">No watchlist matches</td></tr>';
}

async function refreshCatalysts() {
  const resp = await fetch('/api/catalysts');
  if (!resp.ok) return;
  const { catalysts } = await resp.json();
  el('catalysts-body').innerHTML = catalysts.map(c => `
    <div class="catalyst-row">
      <span class="catalyst-date">${c.date}</span>
      <span class="catalyst-days">[${c.days_until}d]</span>
      <span class="catalyst-title">${c.title.replace(/^\[CATALYST\]\s*/, '')}</span>
    </div>
  `).join('') || '<div style="color:var(--muted)">No upcoming catalysts</div>';
}

async function refreshBasket() {
  const resp = await fetch('/api/basket?hours=720');
  if (!resp.ok) return;
  const { positions, excluded_count } = await resp.json();
  el('basket-tbody').innerHTML = positions.map(p => `
    <tr>
      <td class="ticker">${p.ticker}</td>
      <td style="color:var(--muted)">${p.sector}</td>
      <td class="amount">${p.weight_pct.toFixed(1)}%</td>
      <td class="amount">${fmtUsd(p.contract_usd)}</td>
    </tr>
  `).join('') || `<tr><td colspan="4" style="color:var(--muted)">No eligible positions (${excluded_count} excluded)</td></tr>`;
}

async function refreshOptions() {
  const resp = await fetch('/api/options');
  if (!resp.ok) return;
  const { plays } = await resp.json();
  el('options-tbody').innerHTML = plays.map(p => `
    <tr>
      <td class="ticker">${p.ticker}</td>
      <td style="color:${p.action.includes('CALL') ? 'var(--green)' : 'var(--red)'}">${p.action}</td>
      <td style="color:var(--muted);max-width:160px;overflow:hidden;text-overflow:ellipsis">${p.catalyst_date}</td>
      <td class="amount">${p.strike ? '$' + p.strike : '—'}</td>
      <td class="amount">${p.ask ? '$' + p.ask.toFixed(2) : '—'}</td>
    </tr>
  `).join('') || '<tr><td colspan="5" style="color:var(--muted)">No plays. Run govspend ingest first.</td></tr>';
}

// ── Boot ───────────────────────────────────────────────────────────────────
checkAuth();