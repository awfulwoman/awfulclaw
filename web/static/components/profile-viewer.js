/**
 * Minimal markdown renderer for profile files.
 * All source text is HTML-escaped before any tag substitution.
 * Supports: h1-h3, bold, italic, inline code, unordered lists, paragraphs.
 */
function _escape(text) {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function _inline(text) {
  // text is already HTML-escaped — only add safe tags
  return text
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>');
}

function _md(raw) {
  const lines = raw.split('\n');
  const parts = [];
  let inList = false;

  for (const line of lines) {
    const escaped = _escape(line);
    const h3 = escaped.match(/^### (.+)/);
    const h2 = escaped.match(/^## (.+)/);
    const h1 = escaped.match(/^# (.+)/);
    const li = escaped.match(/^[-*] (.+)/);

    if ((h1 || h2 || h3 || escaped.trim() === '') && inList) {
      parts.push('</ul>');
      inList = false;
    }

    if (h3)            parts.push('<h3>' + _inline(h3[1]) + '</h3>');
    else if (h2)       parts.push('<h2>' + _inline(h2[1]) + '</h2>');
    else if (h1)       parts.push('<h1>' + _inline(h1[1]) + '</h1>');
    else if (li)       {
      if (!inList) { parts.push('<ul>'); inList = true; }
      parts.push('<li>' + _inline(li[1]) + '</li>');
    }
    else if (escaped.trim() === '') parts.push('');
    else               parts.push('<p>' + _inline(escaped) + '</p>');
  }

  if (inList) parts.push('</ul>');
  return parts.join('\n');
}

class ProfileViewer extends HTMLElement {
  connectedCallback() {
    this.attachShadow({ mode: 'open' });

    const style = document.createElement('style');
    style.textContent = `
      :host { display: block; }
      h1 { font-size: 1.6em; color: #aac; margin-bottom: 16px; }
      h2 { font-size: 1.2em; color: #99b; margin: 20px 0 8px; }
      h3 { font-size: 1em; color: #889; margin: 16px 0 6px; }
      p, li { color: #ccc; line-height: 1.6; margin-bottom: 8px; }
      ul { padding-left: 20px; margin-bottom: 8px; }
      code { background: #1e1e2e; padding: 2px 6px; border-radius: 4px; font-family: monospace; color: #88aacc; font-size: 0.9em; }
      strong { color: #ddd; }
    `;

    this._content = document.createElement('div');

    const loading = document.createElement('p');
    loading.style.color = '#555';
    loading.style.fontStyle = 'italic';
    loading.textContent = 'Loading\u2026';
    this._content.appendChild(loading);

    this.shadowRoot.appendChild(style);
    this.shadowRoot.appendChild(this._content);

    const name = window.location.pathname.split('/').filter(Boolean).pop() || '';
    this._load(name);
  }

  async _load(name) {
    try {
      const r = await fetch('/proxy/api/info/' + encodeURIComponent(name));
      if (!r.ok) {
        this._content.replaceChildren();
        const err = document.createElement('p');
        err.style.color = '#e88';
        err.textContent = 'Not found.';
        this._content.appendChild(err);
        return;
      }
      const { content } = await r.json();
      // _md() HTML-escapes all source text before generating tags
      this._content.innerHTML = _md(content);
    } catch {
      this._content.replaceChildren();
      const err = document.createElement('p');
      err.style.color = '#e88';
      err.textContent = 'Failed to load.';
      this._content.appendChild(err);
    }
  }
}

customElements.define('profile-viewer', ProfileViewer);
