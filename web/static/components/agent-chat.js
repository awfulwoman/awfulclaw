class AgentChat extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._messages = [];
    this._busy = false;
  }

  connectedCallback() {
    const style = document.createElement('style');
    style.textContent = `
      :host { display: flex; flex-direction: column; height: 100%; }
      .messages { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 10px; }
      .message { max-width: 70%; padding: 8px 12px; border-radius: 12px; line-height: 1.5; word-break: break-word; white-space: pre-wrap; }
      .message.user { align-self: flex-end; background: #1a3a5c; border-radius: 12px 12px 2px 12px; color: #aac; }
      .message.agent { align-self: flex-start; background: #1e1e2e; border-radius: 12px 12px 12px 2px; color: #ccc; }
      .message.error { align-self: flex-start; background: #3c1515; color: #e88; }
      .typing { align-self: flex-start; color: #555; font-size: 13px; padding: 8px 12px; }
      .input-row { display: flex; gap: 8px; padding: 12px 16px; border-top: 1px solid #1e1e2e; }
      textarea { flex: 1; background: #1e1e2e; border: 1px solid #333; border-radius: 8px; padding: 8px 12px; color: #ccc; font-family: inherit; font-size: 14px; resize: none; height: 42px; }
      textarea:focus { outline: none; border-color: #446; }
      button { background: #2a4a7c; border: none; border-radius: 8px; padding: 8px 16px; color: #88aacc; cursor: pointer; font-size: 14px; }
      button:disabled { opacity: 0.4; cursor: default; }
    `;

    this._messagesEl = document.createElement('div');
    this._messagesEl.className = 'messages';

    const inputRow = document.createElement('div');
    inputRow.className = 'input-row';

    this._input = document.createElement('textarea');
    this._input.placeholder = 'Type a message\u2026';
    this._input.rows = 1;

    this._button = document.createElement('button');
    this._button.textContent = 'Send';

    inputRow.appendChild(this._input);
    inputRow.appendChild(this._button);

    this.shadowRoot.appendChild(style);
    this.shadowRoot.appendChild(this._messagesEl);
    this.shadowRoot.appendChild(inputRow);

    this._button.addEventListener('click', () => this._send());
    this._input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); this._send(); }
    });
  }

  _redraw() {
    this._messagesEl.replaceChildren();
    for (const msg of this._messages) {
      const el = document.createElement('div');
      el.className = 'message ' + msg.role + (msg.error ? ' error' : '');
      el.textContent = msg.text;
      this._messagesEl.appendChild(el);
    }
    if (this._busy) {
      const el = document.createElement('div');
      el.className = 'typing';
      el.textContent = 'thinking\u2026';
      this._messagesEl.appendChild(el);
    }
    this._messagesEl.scrollTop = this._messagesEl.scrollHeight;
  }

  async _send() {
    const text = this._input.value.trim();
    if (!text || this._busy) return;
    this._input.value = '';
    this._messages.push({ role: 'user', text });
    this._busy = true;
    this._button.disabled = true;
    this._redraw();

    try {
      const r = await fetch('/proxy/chat', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ message: text }),
      });
      if (!r.ok) {
        this._messages.push({ role: 'agent', error: true, text: 'Agent returned ' + r.status + '.' });
      } else {
        const data = await r.json();
        if (data.error) {
          this._messages.push({ role: 'agent', error: true, text: 'Error: ' + data.error });
        } else {
          this._messages.push({ role: 'agent', text: data.reply });
        }
      }
    } catch {
      this._messages.push({ role: 'agent', error: true, text: 'Failed to reach agent.' });
    } finally {
      this._busy = false;
      this._button.disabled = false;
      this._redraw();
    }
  }
}

customElements.define('agent-chat', AgentChat);
