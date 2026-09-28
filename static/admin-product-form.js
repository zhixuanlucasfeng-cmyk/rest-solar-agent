(function () {
  'use strict';
  const country = document.getElementById('product-country');
  if (!country) return;
  const input = document.getElementById('price_local');
  const field = document.getElementById('local-price-field');
  const currency = document.getElementById('price-currency');

  function updateLocalPrice() {
    const unit = country.selectedOptions[0].dataset.currency || '';
    currency.textContent = unit;
    field.hidden = !unit;
    input.disabled = !unit;
    if (!unit) input.value = '';
  }

  country.addEventListener('change', updateLocalPrice);
  updateLocalPrice();
})();
