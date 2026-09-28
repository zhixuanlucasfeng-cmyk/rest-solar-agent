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

test('queue fields render hostile markup as text and retain selection and status', () => {
  const source = fs.readFileSync(
    path.join(__dirname, '..', 'templates', 'admin', 'inbox.html'), 'utf8',
  );
  const renderQueue = source.match(/function renderQueue\(\) \{[\s\S]*?\n\}/)?.[0];
  assert.ok(renderQueue, 'inbox must render its queue');

  class Element {
    constructor(tagName) {
      this.tagName = tagName;
      this.children = [];
      this.style = {};
      this.text = '';
    }
    set innerHTML(value) {
      assert.equal(value, '', 'queue content must never be parsed as HTML');
      this.children = [];
      this.text = '';
    }
    set textContent(value) {
      this.text = String(value);
      this.children = [];
    }
    get textContent() {
      return this.text + this.children.map(child => child.textContent).join('');
    }
    appendChild(child) {
      this.children.push(child);
      return child;
    }
  }

  const payload = '<img src=x onerror="alert(1)"><script>alert(2)</script>';
  const nodes = { queue: new Element('ul'), 'queue-empty': new Element('p') };
  const created = [];
  const opened = [];
  const context = {
    document: {
      getElementById(id) { return nodes[id]; },
      createElement(tag) {
        const element = new Element(tag);
        created.push(element);
        return element;
      },
    },
    MY_ID: 9,
    openConv: payload,
    queueLabels: { waiting: 'Waiting', you: 'Owned by you', live: 'Live with agent', preview: 'No preview' },
    queue: new Map([
      [payload, { conversation_id: payload, country: payload, preview: payload, mode: 'waiting' }],
      [2, { conversation_id: 2, country: 'NG', agent_id: 9, mode: 'human' }],
      [3, { conversation_id: 3, country: 'NG', agent_id: 10, mode: 'human' }],
    ]),
    openConversation(id) { opened.push(id); },
  };
  vm.runInNewContext(`${renderQueue}\nrenderQueue();`, context);

  const rows = nodes.queue.children;
  assert.equal(rows.length, 3);
  assert.equal(nodes['queue-empty'].style.display, 'none');
  assert.equal(rows[0].className, 'queue-item is-active');
  assert.equal(rows[0].children[0].className, 'queue-item__top');
  assert.equal(rows[0].children[0].children[0].textContent, `#${payload} · ${payload}`);
  assert.equal(rows[0].children[1].className, 'queue-item__preview');
  assert.equal(rows[0].children[1].textContent, payload);
  assert.deepEqual(rows.map(row => row.children[0].children[1].textContent), [
    'Waiting', 'Owned by you', 'Live with agent',
  ]);
  assert.equal(rows[1].children[1].textContent, 'No preview');
  assert.deepEqual(created.map(node => node.tagName), [
    'li', 'div', 'strong', 'span', 'div',
    'li', 'div', 'strong', 'span', 'div',
    'li', 'div', 'strong', 'span', 'div',
  ]);
  assert.ok(created.every(node => node.onerror === undefined && node.onload === undefined));
  rows[0].onclick();
  assert.deepEqual(opened, [payload]);

  context.queue.clear();
  vm.runInNewContext('renderQueue();', context);
  assert.equal(nodes.queue.children.length, 0);
  assert.equal(nodes['queue-empty'].style.display, 'block');
});
