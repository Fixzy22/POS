let cart = [];
let modalProduct = null;
let selectedUnit = 'single';

function formatMoney(amount) {
  const symbol = window.CURRENCY_SYMBOL || 'GH₵';
  return symbol + Number(amount).toFixed(2);
}

function singlesPerUnit(product, unit) {
  if (unit === 'box') return Math.max(1, product.units_per_box);
  if (unit === 'row') return Math.max(1, product.units_per_row);
  return 1;
}

function getUnitPrice(product, unit) {
  if (unit === 'box' && product.price_box > 0) return product.price_box;
  if (unit === 'row' && product.price_row > 0) return product.price_row;
  return product.price * singlesPerUnit(product, unit);
}

function stockForUnit(product, unit) {
  const per = singlesPerUnit(product, unit);
  return Math.floor(product.stock / per);
}

function unitLabel(unit) {
  return { single: 'Single Unit', box: 'Box', row: 'Row' }[unit] || unit;
}

function openUnitModal(el) {
  modalProduct = JSON.parse(el.dataset.product);
  selectedUnit = 'single';
  document.querySelectorAll('.unit-type-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.unit === 'single');
  });
  document.getElementById('modalProductName').textContent = modalProduct.name;
  document.getElementById('modalQty').value = 1;
  updateModalInfo();
  document.getElementById('unitModal').classList.remove('hidden');
}

function closeUnitModal() {
  document.getElementById('unitModal').classList.add('hidden');
  modalProduct = null;
}

function selectUnit(unit) {
  selectedUnit = unit;
  document.querySelectorAll('.unit-type-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.unit === unit);
  });
  updateModalInfo();
}

function updateModalInfo() {
  if (!modalProduct) return;
  const price = getUnitPrice(modalProduct, selectedUnit);
  const stock = stockForUnit(modalProduct, selectedUnit);
  const per = singlesPerUnit(modalProduct, selectedUnit);
  document.getElementById('modalUnitPrice').textContent = formatMoney(price) + ' per ' + unitLabel(selectedUnit).toLowerCase();
  document.getElementById('modalUnitInfo').textContent =
    stock + ' ' + unitLabel(selectedUnit).toLowerCase() + '(s) available' +
    (selectedUnit !== 'single' ? ' (' + per + ' singles each)' : '');
}

function modalQtyChange(delta) {
  const input = document.getElementById('modalQty');
  input.value = Math.max(1, parseInt(input.value || 1) + delta);
}

function confirmAddToCart() {
  if (!modalProduct) return;
  const qty = parseInt(document.getElementById('modalQty').value || 1);
  const stock = stockForUnit(modalProduct, selectedUnit);
  if (qty > stock) {
    alert('Not enough stock for ' + unitLabel(selectedUnit) + '.');
    return;
  }
  const key = modalProduct.id + '-' + selectedUnit;
  const existing = cart.find(i => i.key === key);
  const price = getUnitPrice(modalProduct, selectedUnit);
  if (existing) {
    if (existing.quantity + qty > stock) {
      alert('Not enough stock available.');
      return;
    }
    existing.quantity += qty;
  } else {
    cart.push({
      key,
      product_id: modalProduct.id,
      name: modalProduct.name,
      unit_type: selectedUnit,
      price,
      stock,
      quantity: qty
    });
  }
  closeUnitModal();
  renderCart();
}

function updateQty(key, delta) {
  const item = cart.find(i => i.key === key);
  if (!item) return;
  item.quantity += delta;
  if (item.quantity <= 0) {
    cart = cart.filter(i => i.key !== key);
  } else if (item.quantity > item.stock) {
    item.quantity = item.stock;
    alert('Maximum stock reached.');
  }
  renderCart();
}

function removeItem(key) {
  cart = cart.filter(i => i.key !== key);
  renderCart();
}

function renderCart() {
  const container = document.getElementById('cartItems');
  const totalEl = document.getElementById('cartTotal');
  const btn = document.getElementById('checkoutBtn');

  if (cart.length === 0) {
    container.innerHTML = '<p class="text-slate-500 text-sm">Cart is empty</p>';
    totalEl.textContent = formatMoney(0);
    btn.disabled = true;
    return;
  }

  let total = 0;
  container.innerHTML = cart.map(item => {
    const line = item.price * item.quantity;
    total += line;
    return `
      <div class="flex items-center justify-between bg-slate-800/50 rounded p-2">
        <div class="flex-1 min-w-0">
          <p class="text-sm font-medium truncate">${item.name}</p>
          <p class="text-xs text-slate-500">${unitLabel(item.unit_type)} · ${formatMoney(item.price)} × ${item.quantity}</p>
        </div>
        <div class="flex items-center gap-1 ml-2">
          <button onclick="updateQty('${item.key}', -1)" class="qty-btn">−</button>
          <span class="text-sm w-6 text-center">${item.quantity}</span>
          <button onclick="updateQty('${item.key}', 1)" class="qty-btn">+</button>
          <button onclick="removeItem('${item.key}')" class="text-red-400 text-xs ml-1">✕</button>
        </div>
      </div>`;
  }).join('');

  totalEl.textContent = formatMoney(total);
  btn.disabled = false;
}

function clearCart() {
  cart = [];
  renderCart();
}

async function checkout(options = {}) {
  if (cart.length === 0) return;
  const btn = document.getElementById('checkoutBtn');
  const originalText = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Processing...';

  const customerEl = document.getElementById('customerName');
  try {
    const res = await fetch('/api/checkout', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        items: cart.map(i => ({
          product_id: i.product_id,
          quantity: i.quantity,
          unit_type: i.unit_type
        })),
        payment_method: document.getElementById('paymentMethod').value,
        customer_name: customerEl ? customerEl.value : '',
        notes: document.getElementById('saleNotes').value
      })
    });
    const data = await res.json();
    if (data.success) {
      if (options.print) {
        window.open('/sales/' + data.sale_id + '/receipt?print=1', '_blank');
        window.location.reload();
      } else if (options.redirectReceipt) {
        window.location.href = '/sales/' + data.sale_id + '/receipt?print=1';
      } else {
        alert('Sale complete!\n' + data.sale_number + '\nTotal: ' + formatMoney(data.total));
        window.location.reload();
      }
    } else {
      alert(data.error || 'Checkout failed');
      btn.disabled = false;
      btn.textContent = originalText;
    }
  } catch (e) {
    alert('Network error. Please try again.');
    btn.disabled = false;
    btn.textContent = originalText;
  }
}

function completeAndPrint() {
  checkout({ print: true });
}

function completeSale() {
  checkout({ redirectReceipt: true });
}

function filterProducts() {
  const q = document.getElementById('productSearch').value.toLowerCase();
  document.querySelectorAll('.product-card').forEach(card => {
    const product = JSON.parse(card.dataset.product || '{}');
    const text = (product.name + ' ' + product.sku).toLowerCase();
    card.style.display = text.includes(q) ? '' : 'none';
  });
}
