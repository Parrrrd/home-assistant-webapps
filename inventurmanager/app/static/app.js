function showToast(msg, ok = true) {
  const t = document.getElementById('toast');
  if (!t) return;
  t.textContent = msg;
  t.className = 'toast ' + (ok ? 'toast-ok' : 'toast-err');
  t.classList.add('show');
  window.clearTimeout(window.__toastTimeout);
  window.__toastTimeout = window.setTimeout(() => t.classList.remove('show'), 2400);
}

function copyText(text) {
  const fallback = () => {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.position = 'absolute';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand('copy');
      showToast('Inhalt kopiert.', true);
    } catch (err) {
      showToast('Kopieren fehlgeschlagen.', false);
    }
    document.body.removeChild(ta);
  };
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).then(() => showToast('Inhalt kopiert.', true)).catch(fallback);
  } else {
    fallback();
  }
}

function confirmDeleteForm(formId, message) {
  if (confirm(message)) {
    document.getElementById(formId)?.submit();
  }
}
window.confirmDeleteForm = confirmDeleteForm;

function formatMoneyDe(value) {
  return (value || 0).toLocaleString('de-DE', { style: 'currency', currency: 'EUR' });
}

function parseDeNumber(value) {
  const raw = String(value || '').trim();
  if (!raw) return 0;
  const cleaned = raw.replace(/€/g, '').replace(/\./g, '').replace(',', '.').replace(/[^0-9.-]/g, '');
  const num = parseFloat(cleaned);
  return Number.isFinite(num) ? num : 0;
}


function synthesizePurchaseLabel(purchaseUnit, units, stockUnit, mode) {
  const rawPurchaseUnit = String(purchaseUnit || '').trim();
  const rawStockUnit = String(stockUnit || '').trim();
  const numericUnits = Math.max(parseDeNumber(units || '1'), 1);
  if (mode === 'stock' && numericUnits > 1) {
    const base = rawPurchaseUnit || rawStockUnit;
    if (base && !/^\s*\d/.test(base)) {
      return `${numericUnits.toLocaleString('de-DE')} ${base}`.trim();
    }
  }
  return rawPurchaseUnit || rawStockUnit || '–';
}

let invoiceModeGroupCounter = 0;

function ensureInvoiceModeGroup(row) {
  if (!row) return;
  const radios = row.querySelectorAll('.mode-chip input[type="radio"]');
  if (!radios.length) return;
  invoiceModeGroupCounter += 1;
  const groupName = `import_mode_choice_${invoiceModeGroupCounter}`;
  radios.forEach(input => {
    input.name = groupName;
  });
}

function currentInvoiceRowMode(row) {
  const hidden = row.querySelector('input.import-mode-hidden[name="import_mode[]"]');
  const checked = row.querySelector('.mode-chip input[type="radio"]:checked');
  if (checked && checked.value) return checked.value;
  if (hidden && hidden.value) return hidden.value;
  return 'pack';
}

function updateInvoiceRowPreview(row) {
  if (!row) return;
  const unitsInput = row.querySelector('input[name="units_per_purchase[]"]');
  const qtyInput = row.querySelector('input[name="quantity[]"]');
  const priceInput = row.querySelector('input[name="net_price[]"]');
  const purchaseUnitInput = row.querySelector('input[name="purchase_unit_label[]"]');
  const variantInput = row.querySelector('input[name="variant_label[]"]');
  const modeHidden = row.querySelector('input.import-mode-hidden[name="import_mode[]"]');
  const summary = row.querySelector('.capture-summary');
  const infoValues = row.querySelectorAll('.compact-info-grid .info-value');
  const units = Math.max(parseDeNumber(unitsInput?.value || '1'), 1);
  const qty = Math.max(parseDeNumber(qtyInput?.value || '0'), 0);
  const price = Math.max(parseDeNumber(priceInput?.value || '0'), 0);
  const rawPurchaseUnit = (purchaseUnitInput?.value || '').trim();
  const stockUnit = (variantInput?.value || '').trim() || rawPurchaseUnit || '–';
  const currentMode = currentInvoiceRowMode(row);
  if (modeHidden) modeHidden.value = currentMode;
  const purchaseUnit = synthesizePurchaseLabel(rawPurchaseUnit, units, stockUnit, currentMode);
  const pricePerUnit = units > 0 ? price / units : price;
  if (infoValues.length >= 3) {
    infoValues[0].textContent = purchaseUnit;
    infoValues[1].textContent = price ? formatMoneyDe(price) : '–';
    infoValues[2].textContent = price ? formatMoneyDe(pricePerUnit) : '–';
  }
  if (!summary) return;
  if (!qty || !price) {
    summary.textContent = '';
    return;
  }
  if (currentMode === 'pack') {
    summary.textContent = `Erfasst: ${qty.toLocaleString('de-DE')} Gebinde (${purchaseUnit}) à ${formatMoneyDe(price)}`;
  } else {
    const totalUnits = qty * units;
    summary.textContent = `Erfasst: ${totalUnits.toLocaleString('de-DE')} ${stockUnit} à ${formatMoneyDe(pricePerUnit)}`;
  }
}

function bindModeToggles(row) {
  const hidden = row.querySelector('input.import-mode-hidden[name="import_mode[]"]');
  row.querySelectorAll('.mode-chip input[type="radio"]').forEach(input => {
    input.addEventListener('change', () => {
      if (input.checked && hidden) hidden.value = input.value;
      updateInvoiceRowPreview(row);
    });
  });
}


function getVariantSearchOptions() {
  const dataNode = document.getElementById('variant-search-data');
  if (!dataNode) return [];
  try {
    const parsed = JSON.parse(dataNode.textContent || '[]');
    if (!Array.isArray(parsed)) return [];
    return parsed.map(item => {
      if (typeof item === 'string') {
        return { display_name: item, group_name: item, variant_label: '' };
      }
      return {
        display_name: String(item.display_name || item.group_name || '').trim(),
        group_name: String(item.group_name || item.display_name || '').trim(),
        variant_label: String(item.variant_label || '').trim(),
      };
    }).filter(item => item.display_name || item.group_name);
  } catch (err) {
    return [];
  }
}


function normalizeSearchValue(value) {
  return String(value || '')
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();
}

function getArticleSearchOptions() {
  const node = document.getElementById('article-search-data');
  if (!node) return [];
  try {
    const parsed = JSON.parse(node.textContent || '[]');
    if (!Array.isArray(parsed)) return [];
    return parsed.map(item => ({
      group_id: item.group_id,
      name: String(item.name || '').trim(),
      labels: Array.isArray(item.labels) ? item.labels.map(v => String(v || '').trim()).filter(Boolean) : [],
      aliases: Array.isArray(item.aliases) ? item.aliases.map(v => String(v || '').trim()).filter(Boolean) : [],
    })).filter(item => item.name);
  } catch (err) {
    return [];
  }
}

function scoreArticleOption(item, query) {
  const q = normalizeSearchValue(query);
  if (!q) return 0;
  const name = normalizeSearchValue(item.name);
  const aliases = (item.aliases || []).map(normalizeSearchValue);
  const labels = (item.labels || []).map(normalizeSearchValue);
  const fields = [name, ...aliases, ...labels].filter(Boolean);
  let best = 0;
  fields.forEach(field => {
    if (!field) return;
    if (field === q) best = Math.max(best, 200);
    if (field.startsWith(q)) best = Math.max(best, 160);
    if (field.includes(q)) best = Math.max(best, 130);
    field.split(' ').forEach(word => {
      if (word.startsWith(q)) best = Math.max(best, 145);
      else if (word.includes(q)) best = Math.max(best, 120);
    });
    const ratio = fuzzyRatio(field, q);
    best = Math.max(best, ratio * 100);
  });
  return best;
}

function fuzzyRatio(a, b) {
  a = normalizeSearchValue(a);
  b = normalizeSearchValue(b);
  if (!a || !b) return 0;
  if (a === b) return 1;
  const longer = a.length >= b.length ? a : b;
  const shorter = a.length >= b.length ? b : a;
  if (!longer || !shorter) return 0;
  if (longer.includes(shorter)) return Math.max(shorter.length / longer.length, 0.7);
  // subsequence-ish match
  let i = 0, hits = 0;
  for (const ch of longer) {
    if (i < shorter.length && ch === shorter[i]) {
      hits += 1;
      i += 1;
    }
  }
  return hits / longer.length;
}

function articleSearchMatches(query, limit = 8) {
  const q = String(query || '').trim();
  if (!q) return [];
  const ranked = [];
  getArticleSearchOptions().forEach(item => {
    const score = scoreArticleOption(item, q);
    if (score >= 60) ranked.push({ score, item });
  });
  ranked.sort((a, b) => b.score - a.score || a.item.name.localeCompare(b.item.name, 'de'));
  const seen = new Set();
  const results = [];
  ranked.forEach(entry => {
    const key = normalizeSearchValue(entry.item.name);
    if (seen.has(key)) return;
    seen.add(key);
    results.push(entry.item);
  });
  return results.slice(0, limit);
}

function renderArticleSuggestions(row, query) {
  const input = row.querySelector('.variant-search-input');
  const box = row.querySelector('.search-suggestions');
  const articleNameInput = row.querySelector('input[name="article_name[]"]');
  const variantLabelInput = row.querySelector('input[name="variant_label[]"]');
  const originalArticleInput = row.querySelector('input[name="original_article_name[]"]');
  const statusNode = row.querySelector('.row-split.two-up .muted.small');
  const storageNode = row.querySelector('.storage-status');
  if (!input || !box) return;
  const q = String(query || '').trim();
  if (!q) {
    box.innerHTML = '';
    box.style.display = 'none';
    return;
  }
  const matches = articleSearchMatches(q, 8);
  if (!matches.length) {
    box.innerHTML = '<div class="search-suggestion empty">Kein passender Artikel gefunden</div>';
    box.style.display = 'block';
    return;
  }
  box.innerHTML = matches.map(item => {
    const labels = item.labels && item.labels.length ? item.labels.join(', ') : '–';
    const aliases = item.aliases && item.aliases.length ? `<div class="muted small">Alias: ${item.aliases.slice(0,2).join(', ')}</div>` : '';
    const labelsHtml = `<div class="muted small">Bisher gespeichert als: ${labels}</div>`;
    return `<button type="button" class="search-suggestion" data-name="${item.name.replace(/"/g, '&quot;')}" data-labels="${(item.labels || []).join('||').replace(/"/g,'&quot;')}"><strong>${item.name}</strong>${labelsHtml}${aliases}</button>`;
  }).join('');
  box.style.display = 'block';
  box.querySelectorAll('.search-suggestion[data-name]').forEach(btn => {
    btn.addEventListener('click', () => {
      const chosenName = btn.dataset.name || '';
      const labels = (btn.dataset.labels || '').split('||').filter(Boolean);
      input.value = chosenName;
      if (articleNameInput) articleNameInput.value = chosenName;
      if (originalArticleInput && !originalArticleInput.value.trim()) originalArticleInput.value = chosenName;
      if (variantLabelInput && labels.length === 1) {
        variantLabelInput.value = labels[0];
      }
      if (statusNode) {
        statusNode.textContent = 'Bestehender Artikel ausgewählt';
        statusNode.classList.add('text-ok');
        statusNode.classList.remove('text-warn');
      }
      if (storageNode) {
        storageNode.textContent = labels.length ? `Bisher gespeichert als: ${labels.join(', ')}` : 'Bisher gespeichert als: –';
        storageNode.classList.add('text-ok');
      }
      box.innerHTML = '';
      box.style.display = 'none';
      updateInvoiceRowPreview(row);
    });
  });
}

function bindVariantSearch(row) {
  const input = row.querySelector('.variant-search-input');
  const box = row.querySelector('.search-suggestions');
  if (!input || !box) return;
  const run = () => renderArticleSuggestions(row, input.value);
  input.addEventListener('input', run);
  input.addEventListener('focus', run);
  input.addEventListener('blur', () => {
    window.setTimeout(() => {
      box.style.display = 'none';
    }, 180);
  });
}

function bindInvoiceRow(row) {
  ensureInvoiceModeGroup(row);
  row.querySelector('.remove-row')?.addEventListener('click', function() { row.remove(); updateInventoryTotals(); });
  const articleNameInput = row.querySelector('input[name="article_name[]"]');
  const variantLabelInput = row.querySelector('input[name="variant_label[]"]');
  row.querySelectorAll('input[name="variant_label[]"], input[name="purchase_unit_label[]"], input[name="units_per_purchase[]"], input[name="quantity[]"], input[name="net_price[]"]').forEach(el => {
    el.addEventListener('input', () => updateInvoiceRowPreview(row));
  });
  if (articleNameInput && variantLabelInput) {
    articleNameInput.addEventListener('input', () => {
      if (articleNameInput.value.trim() && !variantLabelInput.value.trim()) {
        variantLabelInput.value = 'Stück';
        updateInvoiceRowPreview(row);
      }
    });
  }
  bindModeToggles(row);
  bindVariantSearch(row);
  updateInvoiceRowPreview(row);
}

function addInvoiceRow() {
  const container = document.getElementById('invoice-rows');
  const template = document.getElementById('invoice-row-template');
  if (!container || !template) return;
  const clone = template.content.cloneNode(true);
  const row = clone.querySelector('.row');
  bindInvoiceRow(row);
  container.appendChild(clone);
}

function bindGenericRemoveRows(root) {
  root.querySelectorAll('.remove-generic-row').forEach(btn => {
    btn.addEventListener('click', () => {
      const card = btn.closest('.article-variant-row');
      if (card) card.remove();
    });
  });
}

function addArticleVariantRow() {
  const container = document.getElementById('article-variant-rows');
  const template = document.getElementById('article-variant-template');
  if (!container || !template) return;
  const clone = template.content.cloneNode(true);
  container.appendChild(clone);
  bindGenericRemoveRows(container);
}

function calculateLayeredInventory(closing, layers, fallbackPrice) {
  if (!closing || closing <= 0) return { total: 0, avg: 0, invalid: false, available: 0 };
  let remaining = closing;
  let total = 0;
  let available = 0;
  const safeLayers = Array.isArray(layers) ? layers : [];
  for (let idx = 0; idx < safeLayers.length; idx += 1) {
    const qty = parseFloat((safeLayers[idx] || {}).quantity || 0) || 0;
    if (qty > 0) available += qty;
  }
  if (closing - available > 1e-9) {
    return { total: null, avg: null, invalid: true, available };
  }
  for (let idx = safeLayers.length - 1; idx >= 0; idx -= 1) {
    if (remaining <= 0) break;
    const layer = safeLayers[idx] || {};
    const qty = parseFloat(layer.quantity || 0) || 0;
    const price = parseFloat(layer.price || 0) || 0;
    if (qty <= 0) continue;
    const take = Math.min(remaining, qty);
    total += take * price;
    remaining -= take;
  }
  return { total, avg: closing > 0 ? total / closing : 0, invalid: false, available };
}

function updateInventoryTotals() {
  const rows = document.querySelectorAll('.inventory-row');
  let total = 0;
  rows.forEach(row => {
    const closing = parseFloat((row.querySelector('.inventory-closing')?.value || '').replace(',', '.')) || 0;
    const priceHidden = row.querySelector('.inventory-price-hidden');
    const priceDisplay = row.querySelector('.inventory-price');
    const errorEl = row.querySelector('.inventory-line-error');
    let layers = [];
    try {
      layers = JSON.parse(row.dataset.layers || '[]');
    } catch (err) {
      layers = [];
    }
    const fallbackPrice = parseFloat((row.dataset.fallbackPrice || '').replace(',', '.')) || 0;
    const calc = calculateLayeredInventory(closing, layers, fallbackPrice);
    const cell = row.querySelector('.inventory-line-total');
    const inline = row.querySelector('.inventory-inline-value');
    if (calc.invalid) {
      if (priceHidden) priceHidden.value = '';
      if (priceDisplay) priceDisplay.value = '–';
      if (cell) cell.textContent = '–';
      if (inline) inline.textContent = '–';
      if (errorEl) {
        errorEl.style.display = 'block';
        errorEl.textContent = `Maximal verfügbar: ${calc.available.toLocaleString('de-DE')} Stück/Gebinde`;
      }
      row.classList.add('inventory-invalid');
      return;
    }
    if (errorEl) {
      errorEl.style.display = 'none';
      errorEl.textContent = '';
    }
    row.classList.remove('inventory-invalid');
    total += calc.total || 0;
    if (priceHidden) {
      priceHidden.value = calc.avg ? calc.avg.toFixed(6) : '0';
    }
    if (priceDisplay) {
      priceDisplay.value = (calc.avg || 0).toLocaleString('de-DE', { style: 'currency', currency: 'EUR' });
    }
    if (cell) {
      cell.textContent = (calc.total || 0).toLocaleString('de-DE', { style: 'currency', currency: 'EUR' });
    }
    if (inline) {
      inline.textContent = (calc.total || 0).toLocaleString('de-DE', { style: 'currency', currency: 'EUR' });
    }
  });
  const totalDisplay = document.getElementById('inventory-total-display');
  if (totalDisplay) {
    totalDisplay.textContent = total.toLocaleString('de-DE', { style: 'currency', currency: 'EUR' });
  }
}


function bindArticleOpenSearch() {
  const input = document.getElementById('article-open-search');
  const box = document.getElementById('article-open-suggestions');
  if (!input || !box) return;
  const render = () => {
    const q = String(input.value || '').trim();
    if (!q) {
      box.innerHTML = '';
      box.style.display = 'none';
      return;
    }
    const matches = articleSearchMatches(q, 12);
    if (!matches.length) {
      box.innerHTML = '<div class="search-suggestion empty">Kein passender Artikel gefunden</div>';
      box.style.display = 'block';
      return;
    }
    box.innerHTML = matches.map(item => {
      const labels = item.labels && item.labels.length ? item.labels.join(', ') : '–';
      return `<a class="search-suggestion" href="/articles/${item.group_id}"><strong>${item.name}</strong><div class="muted small">Bisher gespeichert als: ${labels}</div></a>`;
    }).join('');
    box.style.display = 'block';
  };
  input.addEventListener('input', render);
  input.addEventListener('focus', render);
  input.addEventListener('blur', () => {
    window.setTimeout(() => { box.style.display = 'none'; }, 180);
  });
}

document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('[data-copy-target]').forEach(btn => {
    btn.addEventListener('click', () => {
      const el = document.getElementById(btn.dataset.copyTarget);
      if (!el) return;
      copyText(el.value || el.textContent || '');
    });
  });

  const addBtn = document.getElementById('add-invoice-row');
  if (addBtn) addBtn.addEventListener('click', () => addInvoiceRow());
  const invoiceRows = document.getElementById('invoice-rows');
  if (invoiceRows) {
    invoiceRows.querySelectorAll('.row').forEach(bindInvoiceRow);
  }
  if (invoiceRows && invoiceRows.children.length === 0) {
    addInvoiceRow();
    addInvoiceRow();
  }

  const addVariantBtn = document.getElementById('add-article-variant-row');
  if (addVariantBtn) addVariantBtn.addEventListener('click', () => addArticleVariantRow());
  const articleVariantRows = document.getElementById('article-variant-rows');
  if (articleVariantRows && articleVariantRows.children.length === 0) {
    addArticleVariantRow();
    addArticleVariantRow();
  }

  document.querySelectorAll('.inventory-closing, .inventory-price').forEach(input => {
    input.addEventListener('input', updateInventoryTotals);
  });
  updateInventoryTotals();
  bindArticleOpenSearch();
});

// InventurManager 0.10.35 – mobile navigation and shopping interaction
(function () {
  const sheet = document.getElementById('mobile-more-sheet');
  const openers = document.querySelectorAll('[data-mobile-more]');
  const closers = document.querySelectorAll('[data-mobile-more-close]');
  const setOpen = (open) => {
    if (!sheet) return;
    sheet.classList.toggle('open', open);
    sheet.setAttribute('aria-hidden', open ? 'false' : 'true');
    document.body.style.overflow = open ? 'hidden' : '';
  };
  openers.forEach(btn => btn.addEventListener('click', () => setOpen(true)));
  closers.forEach(btn => btn.addEventListener('click', () => setOpen(false)));

  document.querySelectorAll('[data-shopping-row]').forEach(row => {
    const checkbox = row.querySelector('.shop-check input[type="checkbox"]');
    if (checkbox) {
      checkbox.addEventListener('change', () => row.classList.toggle('is-done', checkbox.checked));
    }
  });
})();
