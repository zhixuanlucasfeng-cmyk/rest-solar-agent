const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

let script = '';
try {
  script = fs.readFileSync(path.join(__dirname, '../static/admin-product-form.js'), 'utf8');
} catch (error) {
  if (error.code !== 'ENOENT') throw error;
}

function form(initialCurrency) {
  const country = {
    selectedOptions: [{ dataset: { currency: initialCurrency } }],
    addEventListener(type, callback) { if (type === 'change') this.change = callback; },
  };
  const input = { value: '125000', disabled: false };
  const field = { hidden: false };
  const currency = { textContent: '' };
  const nodes = { 'product-country': country, price_local: input, 'local-price-field': field, 'price-currency': currency };
  vm.runInNewContext(script, { document: { getElementById: id => nodes[id] } });
  return { country, input, field, currency };
}

test('shared selection hides, disables, and clears the price on initialization', () => {
  const page = form('');
  assert.equal(page.field.hidden, true);
  assert.equal(page.input.disabled, true);
  assert.equal(page.input.value, '');
  assert.equal(page.currency.textContent, '');
});

test('country changes display the fixed currency and returning to Shared clears price', () => {
  const page = form('XAF');
  assert.equal(page.currency.textContent, 'XAF');
  assert.equal(page.input.value, '125000');
  for (const currency of ['XOF', 'NGN', 'SDG', 'XAF']) {
    page.country.selectedOptions = [{ dataset: { currency } }];
    page.country.change();
    assert.equal(page.currency.textContent, currency);
    assert.equal(page.input.disabled, false);
    assert.equal(page.field.hidden, false);
  }
  page.country.selectedOptions = [{ dataset: { currency: '' } }];
  page.country.change();
  assert.equal(page.field.hidden, true);
  assert.equal(page.input.disabled, true);
  assert.equal(page.input.value, '');
  assert.equal(page.currency.textContent, '');
});
