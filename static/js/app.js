/* Rupee Ledger - front-end logic (vanilla JS, no build step).
 * User-supplied text is only ever inserted via textContent / createElement,
 * never innerHTML, so descriptions cannot inject markup. */
(() => {
  'use strict';

  const $ = (sel) => document.querySelector(sel);
  const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
    'August', 'September', 'October', 'November', 'December'];
  const CATEGORY_COLORS = {
    'Food & Dining': '#ff9933', 'Groceries': '#5fd3a1', 'Transport': '#6c8cff',
    'Shopping': '#ff6fa5', 'Bills & Utilities': '#ffd27a', 'Health': '#ff7a7a',
    'Entertainment': '#b28cff', 'Education': '#4fd1e8', 'Travel': '#c8e86a',
    'Rent & Housing': '#e0b3a0', 'Other': '#8d94b3',
  };
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const root = document.documentElement;
  const cssVar = (name) => getComputedStyle(root).getPropertyValue(name).trim();

  // "today" comes from the server so the UI and the insights agree on the date.
  const today = document.body.dataset.today;
  const state = { month: today.slice(0, 7), currentMonth: today.slice(0, 7), category: '', search: '', expenses: [], editingId: null, lastStats: null };
  const seq = { load: 0, coach: 0, suggest: 0, ask: 0 };

  // ---------------------------------------------------------------- formatting
  function groupIndian(digits) {
    if (digits.length <= 3) return digits;
    let head = digits.slice(0, -3);
    const parts = [];
    while (head.length > 2) { parts.unshift(head.slice(-2)); head = head.slice(0, -2); }
    if (head) parts.unshift(head);
    return parts.join(',') + ',' + digits.slice(-3);
  }

  /** ₹12,34,567.00 - mirrors ai_engine.inr() on the server. */
  function inr(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return '\u20B90.00';
    const paise = Math.round(Math.abs(n) * 100);
    const sign = n < 0 && paise > 0 ? '-' : '';
    return `${sign}\u20B9${groupIndian(String(Math.floor(paise / 100)))}.${String(paise % 100).padStart(2, '0')}`;
  }

  /** Short axis labels: ₹950, ₹12,500, ₹1.5L, ₹2Cr. */
  function inrCompact(value) {
    const a = Math.abs(value);
    const sign = value < 0 ? '-' : '';
    const trim = (x) => String(Math.round(x * 100) / 100);
    if (a >= 1e7) return `${sign}\u20B9${trim(a / 1e7)}Cr`;
    if (a >= 1e5) return `${sign}\u20B9${trim(a / 1e5)}L`;
    if (!Number.isInteger(a)) return `${sign}\u20B9${a.toFixed(2)}`;
    return `${sign}\u20B9${groupIndian(String(a))}`;
  }

  const monthLabel = (m) => `${MONTHS[Number(m.slice(5)) - 1]} ${m.slice(0, 4)}`;
  const dateLabel = (d) => `${Number(d.slice(8))} ${MONTHS[Number(d.slice(5, 7)) - 1].slice(0, 3)} ${d.slice(0, 4)}`;

  function shiftMonth(month, delta) {
    let year = Number(month.slice(0, 4));
    let mon = Number(month.slice(5)) + delta;
    while (mon > 12) { mon -= 12; year += 1; }
    while (mon < 1) { mon += 12; year -= 1; }
    return `${year}-${String(mon).padStart(2, '0')}`;
  }

  // ---------------------------------------------------------------- DOM helpers
  function el(tag, props = {}, children = []) {
    const node = document.createElement(tag);
    for (const [key, val] of Object.entries(props)) {
      if (key === 'class') node.className = val;
      else if (key === 'text') node.textContent = val;
      else if (key === 'style') node.style.cssText = val; // CSSOM, allowed even under strict CSP
      else node.setAttribute(key, val);
    }
    for (const child of [].concat(children)) node.append(child);
    return node;
  }

  function toast(message, kind = 'info') {
    const node = el('div', { class: `toast ${kind}`, text: message });
    $('#toasts').append(node);
    setTimeout(() => node.remove(), 4500);
  }

  const counters = new WeakMap();
  /** Animate a number from its previous value; honours prefers-reduced-motion. */
  function countUp(node, target) {
    cancelAnimationFrame(counters.get(node));
    const from = Number(node.dataset.value || 0);
    node.dataset.value = target;
    node.classList.remove('over');
    if (reducedMotion.matches || from === target) { node.textContent = inr(target); return; }
    const start = performance.now();
    const step = (now) => {
      const t = Math.min(1, (now - start) / 700);
      const eased = 1 - Math.pow(1 - t, 3);
      node.textContent = inr(t < 1 ? from + (target - from) * eased : target);
      if (t < 1) counters.set(node, requestAnimationFrame(step));
    };
    counters.set(node, requestAnimationFrame(step));
  }

  function showDash(node) {
    cancelAnimationFrame(counters.get(node));
    delete node.dataset.value;
    node.textContent = '\u2014';
    node.classList.remove('over');
  }

  // ---------------------------------------------------------------- API
  async function api(path, { method = 'GET', body, signal } = {}) {
    const res = await fetch(path, {
      method, signal,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    let data = null;
    try { data = await res.json(); } catch (_) { /* non-JSON error page */ }
    if (!res.ok) throw new Error((data && data.error) || `Request failed (${res.status})`);
    return data;
  }

  // ---------------------------------------------------------------- rendering
  function renderStats(s) {
    countUp($('#stat-total'), s.total);
    $('#stat-count').textContent = `${s.count} expense${s.count === 1 ? '' : 's'}`;
    $('#stat-forecast-sub').textContent = s.period === 'current' ? 'At your current pace' : (s.period === 'past' ? 'Month is over' : 'Month has not started');
    countUp($('#stat-forecast'), s.forecast);

    const remaining = $('#stat-remaining');
    if (s.has_budget) {
      const over = s.remaining < 0;
      $('#stat-remaining-title').textContent = over ? 'Over budget by' : 'Remaining budget';
      countUp(remaining, Math.abs(s.remaining));
      remaining.classList.toggle('over', over);
      $('#stat-remaining-sub').textContent = `of ${inr(s.budget)} (${s.pct_used}% used)`;
    } else {
      $('#stat-remaining-title').textContent = 'Remaining budget';
      showDash(remaining);
      $('#stat-remaining-sub').textContent = 'Set a budget to track this';
    }

    const allowance = $('#stat-allowance');
    if (s.daily_allowance !== null) {
      countUp(allowance, s.daily_allowance);
      $('#stat-allowance-sub').textContent = `for the next ${s.days_left} day${s.days_left === 1 ? '' : 's'}`;
    } else {
      showDash(allowance);
      $('#stat-allowance-sub').textContent = s.has_budget ? 'Month is over' : 'Set a budget first';
    }
  }

  function renderBudget(s) {
    $('#budget-month').textContent = monthLabel(state.month);
    const input = $('#budget-input');
    if (document.activeElement !== input) input.value = s.has_budget ? s.budget : '';
    const pct = s.has_budget ? Math.min(s.pct_used, 100) : 0;
    const bar = $('#budget-bar');
    bar.classList.toggle('over', s.has_budget && s.total > s.budget);
    bar.classList.toggle('warn', s.has_budget && s.total <= s.budget && s.pct_used >= 80);
    bar.setAttribute('aria-valuenow', Math.round(pct));
    $('#budget-fill').style.width = `${pct}%`;
    const text = s.has_budget
      ? `${inr(s.total)} of ${inr(s.budget)} used (${s.pct_used}%)`
      : `No budget set for ${monthLabel(state.month)}.`;
    bar.setAttribute('aria-valuetext', text);
    $('#budget-text').textContent = text;
  }

  const charts = {};
  /** Destroy any previous chart on this canvas, then draw a fresh one (or the empty state). */
  function drawChart(key, name, hasData, makeConfig) {
    const canvas = $(`#${name}-chart`);
    if (charts[key]) { charts[key].destroy(); charts[key] = null; }
    const stale = window.Chart && window.Chart.getChart(canvas);
    if (stale) stale.destroy();
    const empty = $(`#${name}-chart-empty`);
    const box = $(`#${name}-chart-box`);
    if (!window.Chart) {
      box.hidden = true; empty.hidden = false;
      empty.textContent = 'Charts need Chart.js, which could not be loaded (check your internet connection). The data is still listed below.';
      return;
    }
    box.hidden = !hasData; empty.hidden = hasData;
    empty.textContent = 'No spending to chart yet.';
    if (hasData) charts[key] = new window.Chart(canvas, makeConfig());
  }

  function renderCharts(s) {
    if (window.Chart) {
      window.Chart.defaults.color = cssVar('--muted');
      window.Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
    }
    const animation = reducedMotion.matches ? false : { duration: 700 };
    const cats = s.category_totals;
    drawChart('category', 'cat', cats.length > 0, () => ({
      type: 'doughnut',
      data: {
        labels: cats.map((c) => c.category),
        datasets: [{ data: cats.map((c) => c.amount), backgroundColor: cats.map((c) => CATEGORY_COLORS[c.category] || '#8d94b3'), borderColor: cssVar('--ring'), borderWidth: 2 }],
      },
      options: {
        responsive: true, maintainAspectRatio: false, animation, cutout: '62%',
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: (ctx) => ` ${ctx.label}: ${inr(ctx.parsed)} (${cats[ctx.dataIndex].share}%)` } },
        },
      },
    }));

    const [year, mon] = state.month.split('-');
    const todayIndex = state.month === state.currentMonth ? Number(today.slice(8)) - 1 : -1;
    drawChart('daily', 'daily', s.total > 0, () => ({
      type: 'bar',
      data: {
        labels: s.daily.map((_, i) => String(i + 1)),
        datasets: [{ data: s.daily, maxBarThickness: 22, borderRadius: 4,
          backgroundColor: s.daily.map((_, i) => (i === todayIndex ? cssVar('--today-bar') : '#ff9933')) }],
      },
      options: {
        responsive: true, maintainAspectRatio: false, animation,
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: {
            title: (items) => `${items[0].label} ${MONTHS[Number(mon) - 1]} ${year}`,
            label: (ctx) => ` ${inr(ctx.parsed.y)}`,
          } },
        },
        scales: {
          x: { grid: { display: false }, title: { display: true, text: 'Day of month' } },
          y: { beginAtZero: true, ticks: { callback: (v) => inrCompact(v) }, grid: { color: cssVar('--grid') } },
        },
      },
    }));

    const list = $('#breakdown');
    list.replaceChildren(...cats.map((c) => el('li', {}, [
      el('span', { class: 'dot', style: `background:${CATEGORY_COLORS[c.category] || '#8d94b3'}`, 'aria-hidden': 'true' }),
      el('span', { class: 'name', text: c.category }),
      el('span', { class: 'amt', text: c.amount_display }),
      el('span', { class: 'pct', text: `${c.share}%` }),
    ])));
  }

  const LEVEL = { good: ['\u2713', 'Good news'], warn: ['!', 'Warning'], bad: ['\u2715', 'Alert'], info: ['i', 'Note'] };
  function renderCoach(s) {
    $('#insights').replaceChildren(...s.insights.map((item) => el('li', { class: `lvl-${item.level}` }, [
      el('span', { class: 'badge', 'aria-hidden': 'true', text: LEVEL[item.level][0] }),
      el('span', {}, [el('span', { class: 'sr-only', text: `${LEVEL[item.level][1]}: ` }), item.text]),
    ])));
    $('#tips').replaceChildren(...s.tips.map((tip) => el('li', {}, [el('span', { text: tip })])));
  }

  function renderLedger(data) {
    state.expenses = data.expenses;
    $('#expense-list').replaceChildren(...data.expenses.map((e, index) => {
      const color = CATEGORY_COLORS[e.category] || '#8d94b3';
      return el('li', { class: 'expense', style: `--i:${Math.min(index, 14)}` }, [
        el('div', {}, [
          el('div', { class: 'desc', text: e.description }),
          el('div', { class: 'meta' }, [
            el('span', { class: 'dot', style: `background:${color}`, 'aria-hidden': 'true' }),
            el('span', { text: `${e.category} \u00B7 ${dateLabel(e.expense_date)}` }),
          ]),
        ]),
        el('div', { class: 'amount', text: e.amount_display }),
        el('div', { class: 'actions' }, [
          el('button', { type: 'button', class: 'btn ghost small', 'data-action': 'edit', 'data-id': e.id, 'aria-label': `Edit ${e.description}`, text: 'Edit' }),
          el('button', { type: 'button', class: 'btn ghost small danger', 'data-action': 'delete', 'data-id': e.id, 'aria-label': `Delete ${e.description}`, text: 'Delete' }),
        ]),
      ]);
    }));
    $('#empty-state').hidden = data.expenses.length > 0;
    const total = data.stats.count;
    $('#ledger-foot').textContent = data.expenses.length
      ? `Showing ${data.filtered_count} of ${total} \u00B7 ${data.filtered_total_display}`
      : '';
  }

  // ---------------------------------------------------------------- data loading
  async function loadDashboard({ withCoach = false } = {}) {
    const mySeq = ++seq.load;
    const params = new URLSearchParams({ month: state.month });
    if (state.category) params.set('category', state.category);
    if (state.search) params.set('q', state.search);
    let data;
    try {
      data = await api(`/api/dashboard?${params}`);
    } catch (err) {
      if (mySeq === seq.load) toast(err.message, 'error');
      return;
    }
    if (mySeq !== seq.load) return; // a newer request superseded this one
    state.lastStats = data.stats;
    renderStats(data.stats);
    renderBudget(data.stats);
    renderCharts(data.stats);
    renderCoach(data.stats);
    renderLedger(data);
    if (withCoach) loadCoach();
  }

  async function loadCoach() {
    const mySeq = ++seq.coach;
    $('#coach-summary').textContent = 'Thinking\u2026';
    try {
      const data = await api(`/api/coach?month=${state.month}`);
      if (mySeq !== seq.coach) return;
      $('#coach-summary').textContent = data.summary;
    } catch (err) {
      if (mySeq === seq.coach) $('#coach-summary').textContent = 'Could not load the summary.';
    }
  }

  function greeting() {
    const hour = new Date().getHours();
    return `Namaste, good ${hour < 12 ? 'morning' : hour < 17 ? 'afternoon' : 'evening'}.`;
  }

  function setMonth(month) {
    state.month = month;
    $('#month-label').textContent = monthLabel(month);
    $('#hero-sub').textContent = `${greeting()} Here is how ${monthLabel(month)} looks.`;
    $('#prev-month').disabled = month <= '2000-01';
    $('#next-month').disabled = month >= '2100-12';
    $('#export-link').href = `/api/export.csv?month=${month}`;
    $('#add-date').value = month === state.currentMonth ? today : `${month}-01`;
    $('#ask-answer').replaceChildren();
    loadDashboard({ withCoach: true });
  }

  // ---------------------------------------------------------------- live category suggestion
  let suggestTimer = null;
  let suggestCtl = null;
  const suggestion = $('#suggestion');

  function clearSuggestion() {
    clearTimeout(suggestTimer);
    if (suggestCtl) suggestCtl.abort();
    seq.suggest += 1; // invalidate anything still in flight
    suggestion.textContent = '';
  }

  async function fetchSuggestion(text) {
    const mySeq = ++seq.suggest;
    if (suggestCtl) suggestCtl.abort();
    suggestCtl = new AbortController();
    try {
      const r = await api('/api/categorize', { method: 'POST', body: { description: text }, signal: suggestCtl.signal });
      // Ignore late answers for text the user has already changed.
      if (mySeq !== seq.suggest || $('#add-description').value.trim() !== text) return;
      const pct = Math.round(r.confidence * 100);
      const how = r.source === 'llm' ? 'AI' : 'local keyword model';
      suggestion.textContent = r.confidence > 0
        ? `Suggested category: ${r.category} (${how}, ${pct}% sure)`
        : `No match found; this will be filed under ${r.category}.`;
    } catch (err) {
      if (err.name !== 'AbortError' && mySeq === seq.suggest) suggestion.textContent = '';
    }
  }

  $('#add-description').addEventListener('input', (event) => {
    const text = event.target.value.trim();
    clearTimeout(suggestTimer);
    if (text.length < 3) { clearSuggestion(); return; }
    suggestTimer = setTimeout(() => fetchSuggestion(text), 250);
  });

  // ---------------------------------------------------------------- forms
  $('#add-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const description = $('#add-description').value.trim();
    const amount = $('#add-amount').value;
    const when = $('#add-date').value;
    if (!description || !amount || !when) { toast('Please fill in description, amount and date.', 'error'); return; }
    const button = $('#add-submit');
    button.disabled = true;
    try {
      const body = { description, amount: Number(amount), expense_date: when };
      if ($('#add-category').value) body.category = $('#add-category').value;
      const { expense } = await api('/api/expenses', { method: 'POST', body });
      toast(`Added ${expense.amount_display} to ${expense.category}`);
      $('#add-description').value = '';
      $('#add-amount').value = '';
      clearSuggestion();
      $('#add-description').focus();
      const expenseMonth = expense.expense_date.slice(0, 7);
      if (expenseMonth !== state.month) setMonth(expenseMonth);
      else loadDashboard({ withCoach: true });
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      button.disabled = false;
    }
  });

  $('#budget-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const raw = $('#budget-input').value;
    if (raw === '') { toast('Enter a budget amount (0 removes it).', 'error'); return; }
    try {
      const r = await api('/api/budget', { method: 'PUT', body: { month: state.month, amount: Number(raw) } });
      toast(r.budget ? `Budget for ${monthLabel(state.month)} set to ${r.budget_display}` : 'Budget removed');
      loadDashboard({ withCoach: true });
    } catch (err) {
      toast(err.message, 'error');
    }
  });

  $('#ask-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const question = $('#ask-input').value.trim();
    if (!question) return;
    const mySeq = ++seq.ask;
    const answer = $('#ask-answer');
    const button = $('#ask-submit');
    button.disabled = true;
    answer.textContent = 'Thinking\u2026';
    try {
      const r = await api('/api/ask', { method: 'POST', body: { question, month: state.month } });
      if (mySeq !== seq.ask) return;
      answer.replaceChildren(r.answer, el('small', { text: r.source === 'llm' ? 'Answered by OpenAI' : 'Answered by the local engine' }));
    } catch (err) {
      if (mySeq === seq.ask) answer.textContent = err.message;
    } finally {
      if (mySeq === seq.ask) button.disabled = false;
    }
  });

  $('#ask-chips').addEventListener('click', (event) => {
    if (!event.target.classList.contains('chip')) return;
    $('#ask-input').value = event.target.textContent;
    $('#ask-form').requestSubmit();
  });

  // ---------------------------------------------------------------- ledger actions
  const dialog = $('#edit-dialog');

  $('#expense-list').addEventListener('click', async (event) => {
    const button = event.target.closest('button[data-action]');
    if (!button) return;
    const id = Number(button.dataset.id);
    const expense = state.expenses.find((e) => e.id === id);
    if (!expense) return;
    if (button.dataset.action === 'edit') {
      state.editingId = id;
      $('#edit-description').value = expense.description;
      $('#edit-amount').value = expense.amount;
      $('#edit-date').value = expense.expense_date;
      $('#edit-category').value = expense.category;
      dialog.showModal();
    } else if (window.confirm(`Delete "${expense.description}" (${expense.amount_display})?`)) {
      try {
        await api(`/api/expenses/${id}`, { method: 'DELETE' });
        toast('Expense deleted');
        loadDashboard({ withCoach: true });
      } catch (err) {
        toast(err.message, 'error');
      }
    }
  });

  $('#edit-cancel').addEventListener('click', () => dialog.close());
  $('#edit-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = $('#edit-save');
    button.disabled = true;
    try {
      const { expense } = await api(`/api/expenses/${state.editingId}`, {
        method: 'PUT',
        body: {
          description: $('#edit-description').value.trim(),
          amount: Number($('#edit-amount').value),
          expense_date: $('#edit-date').value,
          category: $('#edit-category').value,
        },
      });
      dialog.close();
      toast(`Updated: ${expense.description}`);
      const expenseMonth = expense.expense_date.slice(0, 7);
      if (expenseMonth !== state.month) setMonth(expenseMonth);
      else loadDashboard({ withCoach: true });
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      button.disabled = false;
    }
  });

  $('#filter-category').addEventListener('change', (event) => { state.category = event.target.value; loadDashboard(); });
  let searchTimer = null;
  $('#filter-search').addEventListener('input', (event) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => { state.search = event.target.value.trim(); loadDashboard(); }, 250);
  });

  $('#prev-month').addEventListener('click', () => setMonth(shiftMonth(state.month, -1)));
  $('#next-month').addEventListener('click', () => setMonth(shiftMonth(state.month, 1)));
  $('#this-month').addEventListener('click', () => setMonth(state.currentMonth));

  // ---------------------------------------------------------------- theme switch
  const toggle = $('#theme-toggle');
  function applyTheme(theme, persist) {
    root.dataset.theme = theme;
    toggle.setAttribute('aria-checked', String(theme === 'light'));
    $('meta[name="theme-color"]').content = cssVar('--bg');
    if (persist) {
      try { localStorage.setItem('rupee-ledger-theme', theme); } catch (_) { /* storage blocked */ }
    }
    window.dispatchEvent(new Event('themechange'));
  }
  toggle.addEventListener('click', () => applyTheme(root.dataset.theme === 'light' ? 'dark' : 'light', true));
  // Chart.js draws on a canvas, so it must be redrawn to pick up the new colours.
  window.addEventListener('themechange', () => { if (state.lastStats) renderCharts(state.lastStats); });

  // ---------------------------------------------------------------- floating ₹ coins, glyphs and sparks
  function startParticles() {
    const canvas = $('#particles');
    const ctx = canvas.getContext('2d');
    const font = getComputedStyle(document.body).fontFamily;
    const KINDS = ['glyph', 'glyph', 'coin', 'spark'];
    let width = 0; let height = 0; let particles = []; let frame = null; let rgb = cssVar('--particle');

    const spawn = (anywhere) => ({
      kind: KINDS[Math.floor(Math.random() * KINDS.length)],
      x: Math.random() * width, y: anywhere ? Math.random() * height : height + 40,
      size: 12 + Math.random() * 20, speed: 0.15 + Math.random() * 0.45,
      phase: Math.random() * Math.PI * 2, wobble: 0.004 + Math.random() * 0.01, amp: 0.2 + Math.random() * 0.5,
      alpha: 0.1 + Math.random() * 0.2,
    });
    function resize() {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      width = window.innerWidth; height = window.innerHeight;
      canvas.width = width * dpr; canvas.height = height * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const count = Math.max(16, Math.min(40, Math.round((width * height) / 40000)));
      particles = Array.from({ length: count }, () => spawn(true));
      draw();
    }
    function star(r) {
      ctx.beginPath();
      for (let i = 0; i < 8; i += 1) {
        const radius = i % 2 === 0 ? r : r * 0.28;
        const angle = (Math.PI / 4) * i - Math.PI / 2;
        ctx.lineTo(Math.cos(angle) * radius, Math.sin(angle) * radius);
      }
      ctx.closePath();
    }
    function draw() {
      ctx.clearRect(0, 0, width, height);
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      for (const p of particles) {
        ctx.save();
        ctx.translate(p.x, p.y);
        if (p.kind === 'glyph') {
          ctx.rotate(Math.sin(p.phase) * 0.35);
          ctx.font = `${p.size}px ${font}`;
          ctx.fillStyle = `rgba(${rgb},${p.alpha})`;
          ctx.fillText('\u20B9', 0, 0);
        } else if (p.kind === 'coin') {
          const r = p.size * 0.6;
          ctx.scale(Math.abs(Math.cos(p.phase * 0.6)) * 0.7 + 0.3, 1); // slow coin flip
          ctx.shadowColor = `rgba(${rgb},0.6)`; ctx.shadowBlur = 10;
          ctx.fillStyle = `rgba(${rgb},${p.alpha * 0.55})`;
          ctx.beginPath(); ctx.arc(0, 0, r, 0, Math.PI * 2); ctx.fill();
          ctx.shadowBlur = 0; ctx.lineWidth = 1.2; ctx.strokeStyle = `rgba(${rgb},${p.alpha * 1.6})`; ctx.stroke();
          ctx.font = `${r * 1.1}px ${font}`; ctx.fillStyle = `rgba(${rgb},${Math.min(1, p.alpha * 2.4)})`;
          ctx.fillText('\u20B9', 0, 1);
        } else {
          ctx.shadowColor = `rgba(${rgb},0.8)`; ctx.shadowBlur = 8;
          ctx.fillStyle = `rgba(${rgb},${p.alpha * (0.6 + 0.4 * Math.sin(p.phase * 3))})`;
          star(p.size * 0.4); ctx.fill();
        }
        ctx.restore();
      }
    }
    function tick() {
      for (let i = 0; i < particles.length; i += 1) {
        const p = particles[i];
        p.y -= p.speed; p.phase += p.wobble * 6; p.x += Math.sin(p.phase) * p.amp;
        if (p.y < -50) particles[i] = spawn(false);
      }
      draw();
      frame = requestAnimationFrame(tick);
    }
    function sync() {
      cancelAnimationFrame(frame); frame = null;
      if (!reducedMotion.matches && !document.hidden) frame = requestAnimationFrame(tick);
    }
    window.addEventListener('resize', resize);
    window.addEventListener('themechange', () => { rgb = cssVar('--particle'); draw(); });
    document.addEventListener('visibilitychange', sync);
    reducedMotion.addEventListener('change', sync);
    resize();
    sync();
  }

  /** Background glows drift slightly against the pointer (skipped with reduced motion). */
  function startParallax() {
    let pending = false; let nx = 0; let ny = 0;
    window.addEventListener('pointermove', (event) => {
      if (reducedMotion.matches) return;
      nx = event.clientX / window.innerWidth - 0.5; ny = event.clientY / window.innerHeight - 0.5;
      if (pending) return;
      pending = true;
      requestAnimationFrame(() => {
        root.style.setProperty('--px', nx.toFixed(3)); root.style.setProperty('--py', ny.toFixed(3));
        pending = false;
      });
    }, { passive: true });
  }

  // ---------------------------------------------------------------- boot
  applyTheme(root.dataset.theme === 'light' ? 'light' : 'dark', false);
  startParticles();
  startParallax();
  setMonth(state.month);
})();
