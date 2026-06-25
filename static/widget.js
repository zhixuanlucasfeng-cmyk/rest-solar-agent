/**
 * Rest Solar chat widget.
 * Usage: <script src="/static/widget.js" data-agent-url="https://your-server.com"></script>
 */
(function () {
  const script = document.currentScript;
  const BASE_URL = (script && script.getAttribute('data-agent-url')) || '';
  const SESSION_ID = ([1e7] + -1e3 + -4e3 + -8e3 + -1e11).replace(/[018]/g, c =>
    (c ^ (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (c / 4)))).toString(16));

  const CSS = `
    #rs-widget-btn{position:fixed;bottom:24px;right:24px;width:56px;height:56px;
      border-radius:50%;background:#f59e0b;border:none;cursor:pointer;
      box-shadow:0 4px 20px rgba(0,0,0,.4);z-index:9999;font-size:24px}
    #rs-widget-box{position:fixed;bottom:92px;right:24px;width:340px;
      border-radius:16px;overflow:hidden;display:none;flex-direction:column;
      box-shadow:0 8px 40px rgba(0,0,0,.6);z-index:9999;
      background:#0f172a;font-family:system-ui,sans-serif;max-height:500px}
    #rs-widget-box.open{display:flex}
    #rs-whead{background:#1e293b;padding:12px 16px;display:flex;
      align-items:center;justify-content:space-between;color:#fff;font-size:14px;font-weight:600}
    #rs-wmsg{flex:1;overflow-y:auto;padding:12px;display:flex;flex-direction:column;gap:8px}
    .rs-b{padding:10px 14px;border-radius:14px;font-size:13px;line-height:1.5;max-width:80%}
    .rs-b-u{background:#1e40af;color:#fff;align-self:flex-end;border-radius:14px 14px 4px 14px}
    .rs-b-a{background:#1e293b;color:#e2e8f0;border-radius:14px 14px 14px 4px}
    #rs-winput{display:flex;gap:8px;padding:10px;background:#1e293b;border-top:1px solid #334155}
    #rs-winput input{flex:1;background:#0f172a;border:1px solid #334155;color:#fff;
      border-radius:8px;padding:8px 12px;font-size:13px;outline:none}
    #rs-winput button{background:#f59e0b;border:none;color:#000;font-weight:700;
      padding:8px 14px;border-radius:8px;cursor:pointer;font-size:13px}
  `;
  const style = document.createElement('style');
  style.textContent = CSS;
  document.head.appendChild(style);

  document.body.insertAdjacentHTML('beforeend', `
    <button id="rs-widget-btn" aria-label="Chat with Rest Solar">&#9728;</button>
    <div id="rs-widget-box">
      <div id="rs-whead">
        <span>Rest Solar Assistant</span>
        <button onclick="document.getElementById('rs-widget-box').classList.remove('open')"
          style="background:none;border:none;color:#94a3b8;cursor:pointer;font-size:18px">&#x2715;</button>
      </div>
      <div id="rs-wmsg">
        <div class="rs-b rs-b-a">Hello! Ask me about solar panels, prices, or delivery to Cameroon.</div>
      </div>
      <div id="rs-winput">
        <input id="rs-wi" type="text" placeholder="Type your question...">
        <button id="rs-wsend">&#10148;</button>
      </div>
    </div>
  `);

  document.getElementById('rs-widget-btn').onclick = () =>
    document.getElementById('rs-widget-box').classList.toggle('open');

  async function send() {
    const input = document.getElementById('rs-wi');
    const text = input.value.trim();
    if (!text) return;
    input.value = '';

    const msgs = document.getElementById('rs-wmsg');
    const addBubble = (t, cls) => {
      const d = document.createElement('div');
      d.className = `rs-b ${cls}`;
      d.textContent = t;
      msgs.appendChild(d);
      msgs.scrollTop = msgs.scrollHeight;
      return d;
    };

    addBubble(text, 'rs-b-u');
    const thinking = addBubble('...', 'rs-b-a');

    try {
      const res = await fetch(`${BASE_URL}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, session_id: SESSION_ID }),
      });
      const data = await res.json();
      thinking.textContent = data.reply;
    } catch {
      thinking.textContent = 'Could not connect. Please try again.';
    }
  }

  document.getElementById('rs-wsend').onclick = send;
  document.getElementById('rs-wi').onkeydown = e => { if (e.key === 'Enter') send(); };
})();
