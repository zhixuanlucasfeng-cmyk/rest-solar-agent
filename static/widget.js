(function () {
  const CONV_ID = Math.floor(Math.random() * 1000000);
  const COUNTRY = (document.currentScript && document.currentScript.dataset.country
                   ? document.currentScript.dataset.country
                   : 'CM').toUpperCase();
  const isMobile = window.innerWidth < 768;
  let ws = null;
  let reconnectDelay = 1000;

  function createWidget() {
    const container = document.createElement('div');
    container.id = 'rs-chat-container';
    container.innerHTML = `
      <div id="rs-chat-bubble" style="
        position:fixed; bottom:24px; right:24px; width:56px; height:56px;
        background:#1e40af; border-radius:50%; display:flex; align-items:center;
        justify-content:center; cursor:pointer; box-shadow:0 4px 12px rgba(0,0,0,0.3); z-index:9999;">
        <svg width="24" height="24" fill="white" viewBox="0 0 24 24">
          <path d="M20 2H4a2 2 0 00-2 2v18l4-4h14a2 2 0 002-2V4a2 2 0 00-2-2z"/>
        </svg>
      </div>
      <div id="rs-chat-window" style="
        display:none; position:fixed; z-index:9998; background:white;
        box-shadow:0 8px 32px rgba(0,0,0,0.2); flex-direction:column;
        ${isMobile
          ? 'top:0;left:0;right:0;bottom:0;border-radius:0;'
          : 'bottom:90px;right:24px;width:360px;height:500px;border-radius:16px;'}
      ">
        <div style="background:#1e40af;color:white;padding:16px;border-radius:${isMobile ? '0' : '16px 16px 0 0'};
                    display:flex;justify-content:space-between;align-items:center;">
          <span style="font-weight:600;font-size:16px;">RestarSolar Support</span>
          <button id="rs-close" style="background:none;border:none;color:white;font-size:20px;cursor:pointer;">&#x2715;</button>
        </div>
        <div id="rs-messages" style="flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:8px;"></div>
        <div id="rs-human-bar" style="padding:6px 12px;border-top:1px solid #e5e7eb;text-align:center;">
          <button id="rs-human" style="background:none;border:none;color:#1e40af;font-size:12px;cursor:pointer;text-decoration:underline;">
            Talk to a person
          </button>
        </div>
        <div style="padding:12px;border-top:1px solid #e5e7eb;display:flex;gap:8px;">
          <input id="rs-input" type="text" placeholder="Type a message…"
            style="flex:1;border:1px solid #d1d5db;border-radius:8px;padding:10px 14px;font-size:16px;outline:none;">
          <button id="rs-send" style="background:#1e40af;color:white;border:none;border-radius:8px;
                  padding:10px 16px;cursor:pointer;font-size:14px;">Send</button>
        </div>
      </div>
    `;
    document.body.appendChild(container);

    document.getElementById('rs-chat-bubble').onclick = openChat;
    document.getElementById('rs-close').onclick = closeChat;
    document.getElementById('rs-send').onclick = sendMessage;
    document.getElementById('rs-human').onclick = requestHuman;
    document.getElementById('rs-input').addEventListener('keydown', function (e) {
      if (e.key === 'Enter') sendMessage();
    });
  }

  function connectWS() {
    const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(protocol + '://' + location.host + '/ws/' + CONV_ID + '?country=' + encodeURIComponent(COUNTRY));

    ws.onmessage = function (event) {
      const data = JSON.parse(event.data);
      if (data.type === 'start') {
        appendMessage('assistant', '');
      } else if (data.type === 'token') {
        appendToken(data.text);
      } else if (data.type === 'agent_message') {
        appendMessage('agent', data.text);
      } else if (data.type === 'status') {
        appendMessage('status', data.text);
      }
    };

    ws.onclose = function () {
      setTimeout(function () {
        reconnectDelay = Math.min(reconnectDelay * 2, 30000);
        connectWS();
      }, reconnectDelay);
    };

    ws.onopen = function () { reconnectDelay = 1000; };
  }

  function openChat() {
    document.getElementById('rs-chat-window').style.display = 'flex';
    document.getElementById('rs-chat-bubble').style.display = 'none';
    if (!ws || ws.readyState !== WebSocket.OPEN) connectWS();
  }

  function closeChat() {
    document.getElementById('rs-chat-window').style.display = 'none';
    document.getElementById('rs-chat-bubble').style.display = 'flex';
  }

  function sendMessage() {
    const input = document.getElementById('rs-input');
    const text = input.value.trim();
    if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;
    appendMessage('user', text);
    ws.send(JSON.stringify({ message: text }));
    input.value = '';
  }

  function requestHuman() {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({ action: 'request_human' }));
    document.getElementById('rs-human-bar').style.display = 'none';
  }

  let currentAssistantMsg = null;

  function appendMessage(role, text) {
    const msgs = document.getElementById('rs-messages');
    const div = document.createElement('div');
    div.style.cssText = [
      'max-width:80%; padding:10px 14px; border-radius:12px; font-size:14px; line-height:1.5;',
      role === 'user'
        ? 'align-self:flex-end;background:#1e40af;color:white;border-bottom-right-radius:4px;'
        : role === 'status'
        ? 'align-self:center;background:#f3f4f6;color:#6b7280;font-size:12px;'
        : 'align-self:flex-start;background:#f3f4f6;color:#111;border-bottom-left-radius:4px;'
    ].join('');
    div.textContent = text;
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
    if (role === 'assistant') currentAssistantMsg = div;
    return div;
  }

  function appendToken(token) {
    if (!currentAssistantMsg) appendMessage('assistant', '');
    currentAssistantMsg.textContent += token;
    const msgs = document.getElementById('rs-messages');
    msgs.scrollTop = msgs.scrollHeight;
  }

  createWidget();
})();
