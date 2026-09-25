const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');

function readHandler(templateName, inputId) {
  const template = fs.readFileSync(
    path.join(__dirname, '..', 'templates', 'admin', templateName),
    'utf8',
  );
  const match = template.match(new RegExp(`id="${inputId}"[\\s\\S]*?onkeydown="([^"]+)"`));
  assert.ok(match, `${inputId} must define keyboard behavior`);
  return match[1];
}

const inboxHandler = readHandler('inbox.html', 'reply-input');
const detailHandler = readHandler('conversation_detail.html', 'agent-msg-input');

function runHandler(handler, event) {
  let sends = 0;
  let prevented = 0;
  vm.runInNewContext(handler, {
    event: {
      key: 'Enter',
      ctrlKey: false,
      metaKey: false,
      isComposing: false,
      repeat: false,
      preventDefault() { prevented += 1; },
      ...event,
    },
    sendReply() { sends += 1; },
    sendAgentReply() { sends += 1; },
  });
  return { sends, prevented };
}

test('plain Enter never sends a partial reply', () => {
  assert.deepEqual(runHandler(inboxHandler, {}), { sends: 0, prevented: 0 });
});

test('Ctrl+Enter sends exactly once', () => {
  assert.deepEqual(runHandler(inboxHandler, { ctrlKey: true }), { sends: 1, prevented: 1 });
});

test('composition and repeated Enter events never send', () => {
  assert.deepEqual(
    runHandler(inboxHandler, { ctrlKey: true, isComposing: true }),
    { sends: 0, prevented: 0 },
  );
  assert.deepEqual(
    runHandler(inboxHandler, { ctrlKey: true, repeat: true }),
    { sends: 0, prevented: 0 },
  );
});

test('conversation detail also requires Ctrl/Command+Enter', () => {
  assert.deepEqual(runHandler(detailHandler, {}), { sends: 0, prevented: 0 });
  assert.deepEqual(
    runHandler(detailHandler, { metaKey: true }),
    { sends: 1, prevented: 1 },
  );
});
