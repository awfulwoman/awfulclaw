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
      .sname { font-size: 12px; color: #aaa; }
      .kv-row { font-size: 12px; margin-bottom: 4px; display: flex; gap: 6px; }
      .kv-key { color: #555; }
      .kv-val { color: #888; }
      .sched { font-size: 12px; color: #aaa; margin-bottom: 4px; display: flex; gap: 6px; flex-wrap: wrap; }
      .expr { color: #555; font-size: 11px; }
      .empty { font-size: 12px; color: #333; }
    `;
    this.shadowRoot.appendChild(style);

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
      const r = await fetch('/proxy/api/status');
      if (!r.ok) return;
      const data = await r.json();
      this._renderMcp(data.mcp || {});
      this._renderSchedules(data.schedules || []);
      this._renderKv(data.kv || {});
    } catch { /* silently ignore — stale UI is acceptable */ }
  }

  _renderMcp(mcp) {
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
      row.appendChild(dot);
      row.appendChild(label);
      this._mcpList.appendChild(row);
    }
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
      if (s.cron || s.fire_at) {
        row.appendChild(_el('span', { cls: 'expr', text: s.cron || s.fire_at }));
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
