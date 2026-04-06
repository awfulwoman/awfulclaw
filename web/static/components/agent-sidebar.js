const _DAYS = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
const _MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

function _cronHuman(expr) {
  if (!expr) return '';
  // One-shot ISO datetime
  if (expr.includes('T') || expr.includes('-')) {
    try {
      return new Date(expr).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
    } catch { return expr; }
  }
  const parts = expr.trim().split(/\s+/);
  if (parts.length !== 5) return expr;
  const [min, hour, dom, month, dow] = parts;

  // Build time string
  let time = null;
  if (min !== '*' && hour !== '*') {
    const h = parseInt(hour, 10), m = parseInt(min, 10);
    if (!isNaN(h) && !isNaN(m)) {
      time = `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}`;
    }
  }

  // Build frequency string
  let freq = null;
  if (dow !== '*') {
    const days = dow.split(',').map(d => _DAYS[parseInt(d, 10)] ?? d).join(', ');
    freq = `every ${days}`;
  } else if (dom !== '*') {
    freq = `on day ${dom} of the month`;
  } else if (month !== '*') {
    const months = month.split(',').map(m => _MONTHS[parseInt(m,10)-1] ?? m).join(', ');
    freq = `in ${months}`;
  } else {
    freq = 'daily';
  }

  if (time) return `${freq} at ${time}`;
  if (min === '*' && hour === '*') return freq + ' (every minute)';
  return expr; // fallback
}

function _el(tag, opts = {}) {
  const el = document.createElement(tag);
  if (opts.cls) el.className = opts.cls;
  if (opts.text) el.textContent = opts.text;
  if (opts.href) { el.href = opts.href; }
  return el;
}

class AgentSidebar extends HTMLElement {
  connectedCallback() {
    if (this.shadowRoot) return;
    this.attachShadow({ mode: 'open' });

    const style = document.createElement('style');
    style.textContent = `
      :host { display: block; height: 100%; overflow-y: auto; padding: 16px; background: #10101e; box-sizing: border-box; }
      h3 { font-size: 10px; text-transform: uppercase; letter-spacing: .08em; color: #444; margin: 0 0 8px; }
      .section { margin-bottom: 16px; }
      hr { border: none; border-top: 1px solid #1e1e2e; margin: 12px 0; }
      a { color: #6688bb; text-decoration: none; font-size: 13px; display: block; margin-bottom: 4px; }
      a:hover { color: #88aadd; }
      .server { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
      .dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; background: #6b3030; }
      .dot.on { background: #2d6a4f; }
      .sname { font-size: 12px; color: #aaa; cursor: pointer; }
      .sname:hover { color: #ccc; text-decoration: underline; }
      .popup-overlay { position: fixed; inset: 0; z-index: 1000; display: flex; align-items: center; justify-content: center; }
      .popup { background: #1a1a2e; border: 1px solid #2e2e4e; border-radius: 8px; padding: 16px 20px; min-width: 220px; max-width: 340px; box-shadow: 0 8px 32px #000a; }
      .popup-title { font-size: 13px; font-weight: 600; color: #ccc; margin-bottom: 10px; display: flex; align-items: center; gap: 8px; }
      .popup-tools { list-style: none; margin: 0; padding: 0; }
      .popup-tools li { font-size: 11px; color: #777; padding: 2px 0; font-family: monospace; }
      .popup-tools li::before { content: '⚙ '; color: #444; }
      .popup-empty { font-size: 11px; color: #444; }
      .kv-row { font-size: 12px; margin-bottom: 4px; display: flex; gap: 6px; }
      .kv-key { color: #555; }
      .kv-val { color: #888; }
      .sched { font-size: 12px; color: #aaa; margin-bottom: 4px; display: flex; gap: 6px; flex-wrap: wrap; }
      .expr { color: #555; font-size: 11px; }
      .empty { font-size: 12px; color: #333; }
      .agent-status { display: flex; align-items: center; gap: 7px; margin-bottom: 14px; }
      .agent-label { font-size: 11px; color: #555; }
    `;
    this.shadowRoot.appendChild(style);

    // Agent ping indicator
    const agentRow = _el('div', { cls: 'agent-status' });
    this._agentDot = _el('div', { cls: 'dot' });
    this._agentLabel = _el('span', { cls: 'agent-label', text: 'agent' });
    agentRow.appendChild(this._agentDot);
    agentRow.appendChild(this._agentLabel);
    this.shadowRoot.appendChild(agentRow);
    this.shadowRoot.appendChild(document.createElement('hr'));

    // Profile links (static — no dynamic content)
    const profileSection = this._section('Profile');
    for (const [label, path] of [
      ['Personality', '/info/personality'],
      ['Protocols', '/info/protocols'],
      ['User', '/info/user'],
      ['Check-in', '/info/checkin'],
    ]) {
      const a = _el('a', { text: label + ' \u2192', href: path });
      profileSection.appendChild(a);
    }
    this.shadowRoot.appendChild(profileSection);
    this.shadowRoot.appendChild(document.createElement('hr'));

    this._mcpList = _el('div');
    this._mcpList.appendChild(_el('span', { cls: 'empty', text: 'loading\u2026' }));
    const mcpSection = this._section('MCP Servers');
    mcpSection.appendChild(this._mcpList);
    this.shadowRoot.appendChild(mcpSection);
    this.shadowRoot.appendChild(document.createElement('hr'));

    this._schedList = _el('div');
    this._schedList.appendChild(_el('span', { cls: 'empty', text: 'loading\u2026' }));
    const schedSection = this._section('Schedules');
    schedSection.appendChild(this._schedList);
    this.shadowRoot.appendChild(schedSection);
    this.shadowRoot.appendChild(document.createElement('hr'));

    this._kvList = _el('div');
    this._kvList.appendChild(_el('span', { cls: 'empty', text: 'loading\u2026' }));
    const kvSection = this._section('Config');
    kvSection.appendChild(this._kvList);
    this.shadowRoot.appendChild(kvSection);

    this._load();
    this._interval = setInterval(() => this._load(), 60000);
  }

  disconnectedCallback() {
    clearInterval(this._interval);
  }

  _section(title) {
    const div = _el('div', { cls: 'section' });
    const h3 = _el('h3', { text: title });
    div.appendChild(h3);
    return div;
  }

  async _load() {
    try {
      const ping = await fetch('/proxy/ping');
      const { ok } = await ping.json();
      this._agentDot.className = 'dot' + (ok ? ' on' : '');
      if (!ok) return;
    } catch {
      this._agentDot.className = 'dot';
      return;
    }
    try {
      const r = await fetch('/proxy/api/status');
      if (!r.ok) return;
      const data = await r.json();
      this._renderMcp(data.mcp || {}, data.mcp_details || {});
      this._renderSchedules(data.schedules || []);
      this._renderKv(data.kv || {});
    } catch { /* silently ignore — stale UI is acceptable */ }
  }

  _renderMcp(mcp, details) {
    this._mcpList.replaceChildren();
    const entries = Object.entries(mcp);
    if (!entries.length) {
      this._mcpList.appendChild(_el('span', { cls: 'empty', text: 'none' }));
      return;
    }
    for (const [name, connected] of entries) {
      const row = _el('div', { cls: 'server' });
      const dot = _el('div', { cls: 'dot' + (connected ? ' on' : '') });
      const label = _el('span', { cls: 'sname', text: name });
      const info = details[name] || { connected, tools: [] };
      label.addEventListener('click', () => this._showPopup(name, info));
      row.appendChild(dot);
      row.appendChild(label);
      this._mcpList.appendChild(row);
    }
  }

  _showPopup(name, info) {
    const existing = this.shadowRoot.querySelector('.popup-overlay');
    if (existing) existing.remove();

    const overlay = _el('div', { cls: 'popup-overlay' });
    overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });

    const popup = _el('div', { cls: 'popup' });

    const title = _el('div', { cls: 'popup-title' });
    const dot = _el('div', { cls: 'dot' + (info.connected ? ' on' : '') });
    title.appendChild(dot);
    title.appendChild(document.createTextNode(name));
    popup.appendChild(title);

    if (info.tools && info.tools.length) {
      const ul = _el('ul', { cls: 'popup-tools' });
      for (const t of info.tools) {
        const li = document.createElement('li');
        li.textContent = t;
        ul.appendChild(li);
      }
      popup.appendChild(ul);
    } else {
      popup.appendChild(_el('span', { cls: 'popup-empty', text: info.connected ? 'no tools' : 'disconnected' }));
    }

    overlay.appendChild(popup);
    this.shadowRoot.appendChild(overlay);
  }

  _renderSchedules(schedules) {
    this._schedList.replaceChildren();
    if (!schedules.length) {
      this._schedList.appendChild(_el('span', { cls: 'empty', text: 'none' }));
      return;
    }
    for (const s of schedules) {
      const row = _el('div', { cls: 'sched' });
      row.appendChild(_el('span', { text: s.name }));
      const raw = s.cron || s.fire_at;
      if (raw) {
        const human = _cronHuman(raw);
        const span = _el('span', { cls: 'expr', text: human });
        if (human !== raw) span.title = raw;
        row.appendChild(span);
      }
      this._schedList.appendChild(row);
    }
  }

  _renderKv(kv) {
    this._kvList.replaceChildren();
    const entries = Object.entries(kv);
    if (!entries.length) {
      this._kvList.appendChild(_el('span', { cls: 'empty', text: 'empty' }));
      return;
    }
    for (const [k, v] of entries) {
      const row = _el('div', { cls: 'kv-row' });
      row.appendChild(_el('span', { cls: 'kv-key', text: k }));
      row.appendChild(_el('span', { cls: 'kv-val', text: v }));
      this._kvList.appendChild(row);
    }
  }
}

customElements.define('agent-sidebar', AgentSidebar);
