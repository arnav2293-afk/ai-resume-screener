/* CIN & LLPIN Checker: UI. Depends on validator.js (window.CinValidator). */
(function () {
  'use strict';
  var V = window.CinValidator;
  var $ = function (id) { return document.getElementById(id); };
  var el = {
    ids: $('ids'), lineCount: $('line-count'), error: $('ids-error'),
    check: $('check-btn'), sample: $('sample-btn'), clear: $('clear-btn'),
    empty: $('empty-state'), results: $('results'), sub: $('results-sub'),
    tiles: $('tiles'), notice: $('notice'), chips: $('chips'), search: $('search'), sort: $('sort'),
    tbody: $('tbody'), tableEmpty: $('table-empty'), table: $('table'), pager: $('pager'),
    copyInvalid: $('copy-invalid-btn'), exportBtn: $('export-btn'),
    help: $('help'), toast: $('toast')
  };

  var SAMPLE = [
    'L17110MH1973PLC019786', 'U72200KA2008PTC045678', 'U74999DL2019OPC351234',
    'U40100TN1957GOI002345', 'AAB-1234', 'U72200XX2015PTC123456',
    'L17110MH2031PLC019786', 'U72200KA2008ABC045678', 'U7220KA2008PTC04567',
    'AB-12345', 'u72200ka2008ptc045678', 'ABCDE1234F'
  ].join('\n');

  var PAGE = 100;
  var state = { data: [], truncated: false, max: 5000, filter: 'all', q: '', sort: 'problems', limit: PAGE, open: {}, checked: false };

  /* ---------- helpers ---------- */
  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function fmt(n) { return n.toLocaleString('en-IN'); }
  function plural(n, one, many) { return fmt(n) + ' ' + (n === 1 ? one : (many || one + 's')); }
  var toastTimer;
  function toast(msg) {
    el.toast.textContent = msg; el.toast.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(function () { el.toast.hidden = true; }, 2200);
  }
  function copy(text) {
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
    var t = document.createElement('textarea'); t.value = text; t.style.position = 'fixed'; t.style.opacity = '0';
    document.body.appendChild(t); t.select();
    try { document.execCommand('copy'); } finally { document.body.removeChild(t); }
    return Promise.resolve();
  }
  var CHEVRON = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>';

  /* ---------- segments ---------- */
  function segsHtml(segments) {
    return segments.map(function (s) {
      var cls = 'seg seg--' + s.key + (s.bad ? ' is-bad' : '') + (s.missing ? ' is-missing' : '');
      return '<div class="' + cls + '">' +
        '<span class="seg__chars">' + esc(s.chars) + '</span>' +
        (s.label ? '<span class="seg__label">' + esc(s.label) + '</span>' : '<span class="seg__label">&nbsp;</span>') +
        (s.meaning ? '<span class="seg__meaning">' + esc(s.meaning) + '</span>' : '') +
        '</div>';
    }).join('');
  }

  /* ---------- input ---------- */
  function countIds(text) {
    var n = 0;
    String(text).split(/\r\n|\r|\n/).forEach(function (l) {
      l.split(/[,;\t]/).forEach(function (p) { if (p.trim()) n++; });
    });
    return n;
  }
  function updateCount() {
    var n = countIds(el.ids.value);
    el.clear.hidden = !el.ids.value.length;
    if (!n) { el.lineCount.textContent = 'No IDs yet'; el.lineCount.style.color = ''; return; }
    if (n > state.max) {
      el.lineCount.textContent = fmt(n) + ' IDs · only the first ' + fmt(state.max) + ' will be checked';
      el.lineCount.style.color = 'var(--warning)';
    } else {
      el.lineCount.textContent = plural(n, 'ID');
      el.lineCount.style.color = '';
    }
  }
  function showError(msg) {
    el.error.textContent = msg; el.error.hidden = !msg;
    if (msg) el.ids.setAttribute('aria-invalid', 'true'); else el.ids.removeAttribute('aria-invalid');
  }

  /* ---------- run ---------- */
  function run(opts) {
    opts = opts || {};
    var out = V.validateText(el.ids.value, { max: state.max });
    if (!out.results.length) {
      if (opts.fromButton) {
        showError(el.ids.value.trim() ? 'We couldn’t find any IDs. Put one CIN or LLPIN on each line.' : 'Paste at least one CIN or LLPIN first.');
        el.ids.focus();
      }
      state.checked = false; state.data = [];
      el.results.hidden = true; el.empty.hidden = false;
      el.check.textContent = 'Check IDs';
      return;
    }
    showError('');
    state.data = out.results; state.truncated = out.truncated; state.checked = true;
    state.limit = PAGE; state.open = {};
    if (opts.resetFilters) { state.filter = 'all'; state.q = ''; el.search.value = ''; }
    el.empty.hidden = true; el.results.hidden = false;
    el.check.textContent = 'Check again';
    render();
    if (opts.scroll) el.results.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  /* ---------- derived counts ---------- */
  var FILTERS = [
    { key: 'all', label: 'All', test: function () { return true; } },
    { key: 'invalid', label: 'Invalid', test: function (r) { return !r.valid; } },
    { key: 'valid', label: 'Valid', test: function (r) { return r.valid; } },
    { key: 'companies', label: 'Companies', test: function (r) { return r.valid && r.kind === 'CIN'; } },
    { key: 'llps', label: 'LLPs', test: function (r) { return r.valid && r.kind === 'LLPIN'; } },
    { key: 'listed', label: 'Listed', test: function (r) { return r.valid && r.fields.listed === 'Listed'; } },
    { key: 'unlisted', label: 'Unlisted', test: function (r) { return r.valid && r.fields.listed === 'Unlisted'; } },
    { key: 'dups', label: 'Duplicates', test: function (r) { return !!r.duplicateOf; } }
  ];
  function count(key) {
    var f = FILTERS.filter(function (x) { return x.key === key; })[0];
    return state.data.filter(f.test).length;
  }

  function visibleRows() {
    var f = FILTERS.filter(function (x) { return x.key === state.filter; })[0];
    var q = state.q.trim().toLowerCase();
    var rows = state.data.filter(function (r) {
      if (!f.test(r)) return false;
      if (!q) return true;
      var hay = [r.id, r.input, r.fields.state, r.fields.typeName, r.fields.listed, r.kind, r.fields.year]
        .concat(r.errors.map(function (e) { return e.msg; })).join(' ').toLowerCase();
      return hay.indexOf(q) !== -1;
    });
    if (state.sort === 'problems') rows.sort(function (a, b) { return (a.valid - b.valid) || (a.line - b.line); });
    else if (state.sort === 'az') rows.sort(function (a, b) { return a.id < b.id ? -1 : a.id > b.id ? 1 : a.line - b.line; });
    else rows.sort(function (a, b) { return a.line - b.line; });
    return rows;
  }

  /* ---------- render ---------- */
  function render() {
    renderSummary(); renderTiles(); renderChips(); renderTable();
  }

  function renderSummary() {
    var total = state.data.length, inv = count('invalid'), dups = count('dups');
    var parts = [plural(total, 'ID') + ' checked', fmt(total - inv) + ' valid', fmt(inv) + ' invalid'];
    if (dups) parts.push(plural(dups, 'duplicate'));
    el.sub.textContent = parts.join(' · ');
    el.copyInvalid.disabled = !inv;
    el.copyInvalid.textContent = inv ? 'Copy ' + plural(inv, 'invalid ID') : 'No invalid IDs';
    if (state.truncated) {
      el.notice.hidden = false;
      el.notice.textContent = 'Your list has more than ' + fmt(state.max) + ' IDs, so only the first ' + fmt(state.max) + ' were checked. Split longer lists into batches.';
    } else el.notice.hidden = true;
  }

  function renderTiles() {
    var total = state.data.length, valid = count('valid'), inv = total - valid;
    var cos = count('companies'), llps = count('llps'), listed = count('listed');
    var pct = function (n) { return total ? Math.round(n / total * 100) : 0; };
    var tiles = [
      { f: 'valid', label: 'Valid', value: valid, sub: pct(valid) + '% of ' + fmt(total) + ' checked', dot: 'var(--success)', track: 'var(--success-tint)', meter: valid / total },
      { f: 'invalid', label: 'Invalid', value: inv, sub: inv ? 'Fix these before filing' : 'Nothing to fix', dot: 'var(--error)', track: 'var(--error-tint)', meter: inv / total },
      { f: 'companies', label: 'Companies', value: cos, sub: cos ? fmt(listed) + ' listed · ' + fmt(cos - listed) + ' unlisted' : 'No valid CINs', dot: 'var(--seg-industry)' },
      { f: 'llps', label: 'LLPs', value: llps, sub: llps ? 'LLPINs have no state or year' : 'No valid LLPINs', dot: 'var(--brand)' }
    ];
    el.tiles.innerHTML = tiles.map(function (t) {
      return '<button type="button" class="tile" data-filter="' + t.f + '" aria-pressed="' + (state.filter === t.f) + '"' +
        ' style="--dot:' + t.dot + (t.track ? ';--track:' + t.track : '') + '"' +
        ' aria-label="' + esc(t.label + ': ' + t.value + '. ' + t.sub + '. Show only these') + '">' +
        '<span class="tile__label"><span class="tile__dot"></span>' + t.label + '</span>' +
        '<span class="tile__value">' + fmt(t.value) + '</span>' +
        '<span class="tile__sub">' + esc(t.sub) + '</span>' +
        (t.meter !== undefined ? '<span class="meter" aria-hidden="true"><span style="width:' + (t.meter * 100).toFixed(1) + '%"></span></span>' : '') +
        '</button>';
    }).join('');
  }

  function renderChips() {
    el.chips.innerHTML = FILTERS.map(function (f) {
      var n = count(f.key);
      if (!n && ['all', 'invalid', 'valid'].indexOf(f.key) === -1 && state.filter !== f.key) return '';
      return '<button type="button" class="chip" data-filter="' + f.key + '" aria-pressed="' + (state.filter === f.key) + '">' +
        f.label + '<span class="count">' + fmt(n) + '</span></button>';
    }).join('');
  }

  function cell(value, label, bad, extraClass) {
    var faint = value === '—';
    var cls = (faint ? 'cell-faint is-empty-sm ' : '') + (extraClass || '');
    var inner = bad ? '<span class="bad-field">' + esc(value) + '</span>' : esc(value);
    return '<td data-label="' + label + '"' + (cls.trim() ? ' class="' + cls.trim() + '"' : '') + '>' + inner + '</td>';
  }

  function detailsText(r) {
    if (!r.valid) {
      var more = r.errors.length > 1 ? ' <span class="more">+' + (r.errors.length - 1) + ' more</span>' : '';
      return { html: esc(r.errors[0].msg) + more, cls: 'is-error' };
    }
    var bits = [];
    if (r.duplicateOf) bits.push('Same ID as line ' + r.duplicateOf);
    if (r.kind === 'LLPIN') bits.push('No state or year in an LLPIN');
    if (r.notes.length) bits.push(r.notes.join(', '));
    return bits.length ? { html: esc(bits.join(' · ')), cls: r.kind === 'LLPIN' || r.duplicateOf ? 'keep-sm' : '' } : { html: '—', cls: 'cell-faint' };
  }

  // One-line summary used on phones instead of five labelled columns.
  function factsHtml(r) {
    var b = r.badFields || {};
    var bits;
    if (r.kind === 'LLPIN') bits = [['LLP']];
    else if (r.kind === 'CIN' && r.segments.length === 6) {
      bits = [[r.fields.listed, b.listed], [r.fields.type, b.type], [r.fields.state, b.state], [r.fields.year, b.year]];
    } else return '<td class="cell-facts is-empty-sm"></td>';
    return '<td class="cell-facts">' + bits.map(function (x) {
      return x[1] ? '<span class="bad-field">' + esc(x[0]) + '</span>' : esc(x[0]);
    }).join(' · ') + '</td>';
  }

  function rowHtml(r, idx) {
    var open = !!state.open[idx];
    var b = r.badFields || {};
    var d = detailsText(r);
    var badges = '<span class="badge ' + (r.valid ? 'badge--valid">Valid' : 'badge--invalid">Invalid') + '</span>' +
      (r.duplicateOf ? '<span class="badge badge--dup">Duplicate</span>' : '');
    var html = '<tr class="row ' + (r.valid ? 'is-valid' : 'is-invalid') + (open ? ' is-open' : '') + '" data-idx="' + idx + '">' +
      '<td class="cell-line"><span class="sm-only">Line </span>' + r.line + '</td>' +
      '<td class="cell-id">' + esc(r.id || r.input) + '</td>' +
      '<td class="cell-status"><div class="badges">' + badges + '</div></td>' +
      factsHtml(r) +
      cell(r.kind === 'CIN' ? 'Company' : r.kind === 'LLPIN' ? 'LLP' : '—', 'Kind') +
      cell(r.fields.listed, 'Listed', b.listed) +
      cell(r.fields.state, 'State', b.state) +
      cell(r.fields.year, 'Year', b.year) +
      cell(r.fields.type, 'Type', b.type, 'cell-type') +
      '<td class="cell-details ' + d.cls + '">' + d.html + '</td>' +
      '<td class="cell-toggle"><button type="button" class="toggle" aria-expanded="' + open + '" aria-controls="detail-' + idx + '">' +
      CHEVRON + '<span class="toggle__text">' + (open ? 'Hide breakdown' : 'Show breakdown') + '</span>' +
      '<span class="sr-only"> for ' + esc(r.id) + '</span></button></td>' +
      '</tr>';
    if (open) html += detailHtml(r, idx);
    return html;
  }

  function detailHtml(r, idx) {
    var meta = [];
    if (r.kind === 'CIN' && r.segments.length === 6) {
      meta.push('Industry code (NIC): <strong class="mono">' + esc(r.fields.industry) + '</strong>');
      meta.push('Registration no.: <strong class="mono">' + esc(r.fields.reg) + '</strong>');
    }
    if (r.input.trim() !== r.id) meta.push('You typed: <span class="mono">' + esc(r.input.trim()) + '</span>');
    if (r.duplicateOf) meta.push('Same ID as line ' + r.duplicateOf);
    var body = r.valid
      ? '<p class="detail__summary">' + esc(r.summary) + '</p>'
      : '<ul class="detail__errors">' + r.errors.map(function (e) { return '<li>' + esc(e.msg) + '</li>'; }).join('') + '</ul>';
    return '<tr class="detail" id="detail-' + idx + '"><td colspan="10"><div class="detail__inner">' +
      '<div class="segs">' + segsHtml(r.segments) + '</div>' + body +
      '<div class="detail__meta">' + meta.map(function (m) { return '<span>' + m + '</span>'; }).join('') +
      '<button type="button" class="btn btn--secondary btn--sm" data-copy="' + esc(r.id) + '">Copy ID</button></div>' +
      '</div></td></tr>';
  }

  function renderTable() {
    var rows = visibleRows();
    state.visible = rows;
    var shown = rows.slice(0, state.limit);
    el.tbody.innerHTML = shown.map(function (r) { return rowHtml(r, state.data.indexOf(r)); }).join('');
    el.table.hidden = !rows.length;
    el.tableEmpty.hidden = !!rows.length;
    if (!rows.length) {
      el.tableEmpty.innerHTML = '<h3>No results match</h3><p class="muted">' +
        (state.q ? 'Nothing matches “' + esc(state.q) + '”. ' : 'Nothing in this filter. ') +
        '</p><button type="button" class="btn btn--secondary btn--sm" data-reset>Show all results</button>';
    }
    var label = state.filter === 'all' && !state.q ? '' : ' (' + fmt(rows.length) + ')';
    el.exportBtn.textContent = 'Export CSV' + label;
    if (rows.length > shown.length) {
      var next = Math.min(PAGE, rows.length - shown.length);
      el.pager.innerHTML = '<span>Showing ' + fmt(shown.length) + ' of ' + fmt(rows.length) + '</span>' +
        '<button type="button" class="btn btn--secondary btn--sm" data-more>Show ' + fmt(next) + ' more</button>' +
        (rows.length <= 2000 ? '<button type="button" class="link-btn" data-all>Show all</button>' : '');
    } else {
      el.pager.innerHTML = rows.length > 12 ? '<span>Showing all ' + fmt(rows.length) + '</span>' : '';
    }
  }

  function toggleRow(idx) {
    if (state.open[idx]) delete state.open[idx]; else state.open[idx] = true;
    var tr = el.tbody.querySelector('tr.row[data-idx="' + idx + '"]');
    if (!tr) return;
    var next = tr.nextElementSibling;
    if (next && next.classList.contains('detail')) next.remove();
    var tmp = document.createElement('tbody');
    tmp.innerHTML = rowHtml(state.data[idx], idx);
    var newRow = tmp.firstElementChild;
    tr.replaceWith(newRow);
    if (tmp.firstElementChild) newRow.after(tmp.firstElementChild);
    newRow.querySelector('.toggle').focus({ preventScroll: true });
  }

  /* ---------- CSV ---------- */
  function exportCsv() {
    var rows = state.visible || state.data;
    var head = ['Line', 'You typed', 'ID', 'Status', 'Kind', 'Listed', 'State', 'Year', 'Company type', 'Problems', 'Notes'];
    var q = function (v) { v = v == null ? '' : String(v); return /[",\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; };
    var lines = [head.join(',')].concat(rows.map(function (r) {
      var notes = r.notes.slice(); if (r.duplicateOf) notes.push('Duplicate of line ' + r.duplicateOf);
      return [r.line, r.input.trim(), r.id, r.valid ? 'Valid' : 'Invalid',
        r.kind === 'CIN' ? 'Company' : r.kind === 'LLPIN' ? 'LLP' : '',
        r.fields.listed, r.fields.state, r.fields.year, r.fields.typeName,
        r.errors.map(function (e) { return e.msg; }).join(' '), notes.join('; ')].map(function (v) { return q(v === '—' ? '' : v); }).join(',');
    }));
    var blob = new Blob(['﻿' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8' });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'cin-check-' + new Date().toISOString().slice(0, 10) + '.csv';
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
    toast('Downloaded ' + plural(rows.length, 'row'));
  }

  /* ---------- 500-line test data ---------- */
  function make500() {
    var seed = 7;
    var rnd = function () { seed = (seed * 16807) % 2147483647; return (seed - 1) / 2147483646; };
    var pick = function (a) { return a[Math.floor(rnd() * a.length)]; };
    var pad = function (n, w) { n = String(n); while (n.length < w) n = '0' + n; return n; };
    var states = Object.keys(V.STATES), types = ['PLC', 'PTC', 'PTC', 'PTC', 'OPC', 'GOI', 'NPL'];
    var nic = ['17110', '72200', '74999', '40100', '65910', '51909', '45201', '85110', '62099', '70100'];
    var out = [];
    for (var i = 0; i < 500; i++) {
      var r = rnd();
      if (r < 0.12) {
        out.push(String.fromCharCode(65 + Math.floor(rnd() * 26), 65 + Math.floor(rnd() * 26), 65 + Math.floor(rnd() * 26)) + '-' + pad(Math.floor(rnd() * 9999), 4));
        continue;
      }
      var type = pick(types);
      var year = type === 'OPC' ? 2014 + Math.floor(rnd() * 12) : 1950 + Math.floor(rnd() * 76);
      var listing = (type === 'PLC' && rnd() < 0.4) ? 'L' : 'U';
      var cin = listing + pick(nic) + pick(states) + year + type + pad(Math.floor(rnd() * 999999), 6);
      if (r > 0.82) { // break it in a realistic way
        var how = Math.floor(rnd() * 5);
        if (how === 0) cin = cin.slice(0, 6) + pick(['XX', 'OD', 'ZZ', 'TS']) + cin.slice(8);
        else if (how === 1) cin = cin.slice(0, 8) + (2027 + Math.floor(rnd() * 10)) + cin.slice(12);
        else if (how === 2) cin = cin.slice(0, 12) + pick(['ABC', 'PVT', 'LTD']) + cin.slice(15);
        else if (how === 3) cin = cin.slice(0, 20);
        else cin = cin.slice(0, 16) + 'O' + cin.slice(17);
      }
      if (rnd() < 0.05) cin = cin.toLowerCase();
      out.push(cin);
    }
    return out.join('\n');
  }

  /* ---------- help dialog ---------- */
  function fillHelp() {
    var example = V.validate('L17110MH1973PLC019786', 1).segments;
    $('anatomy-cin').innerHTML = segsHtml(example);
    $('help-cin').innerHTML = segsHtml(example);
    $('anatomy-llp').innerHTML = segsHtml(V.validate('AAB-1234', 1).segments);
    $('help-types').innerHTML = Object.keys(V.TYPES).map(function (k) {
      return '<div><dt>' + k + '</dt><dd>' + esc(V.TYPES[k].name) + '</dd></div>';
    }).join('');
    $('help-states').innerHTML = Object.keys(V.STATES).sort(function (a, b) { return V.STATES[a] < V.STATES[b] ? -1 : 1; }).map(function (k) {
      return '<div><dt>' + k + '</dt><dd>' + esc(V.STATES[k]) + '</dd></div>';
    }).join('');
  }

  /* ---------- events ---------- */
  var debounce;
  el.ids.addEventListener('input', function () {
    updateCount();
    if (el.error.textContent) showError('');
    if (!state.checked && !el.ids.value.trim()) return;
    if (state.checked) {
      clearTimeout(debounce);
      debounce = setTimeout(function () { run(); }, 250);
    }
  });
  el.ids.addEventListener('paste', function () {
    setTimeout(function () { updateCount(); run({ resetFilters: !state.checked }); }, 0);
  });
  el.ids.addEventListener('keydown', function (e) {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); run({ fromButton: true, scroll: true }); }
  });
  el.check.addEventListener('click', function () { run({ fromButton: true, scroll: true }); });
  el.sample.addEventListener('click', function () {
    el.ids.value = SAMPLE; updateCount(); run({ resetFilters: true, scroll: true });
  });
  el.clear.addEventListener('click', function () {
    el.ids.value = ''; updateCount(); showError('');
    state.checked = false; state.data = []; state.filter = 'all'; state.q = ''; el.search.value = '';
    el.results.hidden = true; el.empty.hidden = false; el.check.textContent = 'Check IDs';
    el.ids.focus();
  });
  document.addEventListener('click', function (e) {
    var t = e.target;
    var f = t.closest('[data-filter]');
    if (f) {
      var key = f.getAttribute('data-filter');
      state.filter = (f.classList.contains('tile') && state.filter === key) ? 'all' : key;
      state.limit = PAGE; renderTiles(); renderChips(); renderTable(); return;
    }
    var c = t.closest('[data-copy]');
    if (c) { copy(c.getAttribute('data-copy')).then(function () { toast('Copied ' + c.getAttribute('data-copy')); }); return; }
    if (t.closest('[data-more]')) { state.limit += PAGE; renderTable(); return; }
    if (t.closest('[data-all]')) { state.limit = Infinity; renderTable(); return; }
    if (t.closest('[data-reset]')) { state.filter = 'all'; state.q = ''; el.search.value = ''; render(); return; }
    if (t.closest('[data-open-help]')) { el.help.showModal(); return; }
    if (t.closest('[data-close-help]') || t === el.help) { el.help.close(); return; }
    if (t.closest('[data-load-500]')) { el.ids.value = make500(); updateCount(); run({ resetFilters: true, scroll: true }); return; }
    var row = t.closest('tr.row');
    if (row && !window.getSelection().toString()) toggleRow(Number(row.getAttribute('data-idx')));
  });
  el.search.addEventListener('input', function () { state.q = el.search.value; state.limit = PAGE; renderTable(); });
  el.sort.addEventListener('change', function () { state.sort = el.sort.value; renderTable(); });
  el.exportBtn.addEventListener('click', exportCsv);
  el.copyInvalid.addEventListener('click', function () {
    var ids = state.data.filter(function (r) { return !r.valid; }).map(function (r) { return r.input.trim(); });
    if (!ids.length) return;
    copy(ids.join('\n')).then(function () { toast('Copied ' + plural(ids.length, 'invalid ID')); });
  });

  fillHelp();
  updateCount();
})();
