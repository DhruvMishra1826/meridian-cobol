import { state } from './state.js';
import { $, connection, notify, makeEmpty } from './dom.js';
import { views, reportNames } from './catalog.js';
import { api, report } from './api.js';
import {
  updateSummary,
  renderTable,
  filteredTable,
  reportCommand,
  configureReport,
  exportCSV,
} from './reports.js';
export async function refresh() {
  const generation = ++state.generation;
  const currentView = state.view;
  $('refresh-button').disabled = true;
  try {
    if (currentView === 'overview') {
      const [summary, accounts, reorder] = await Promise.all([
        api('/api/health'),
        report('ACCOUNTS'),
        report('REORDER'),
      ]);
      if (generation !== state.generation) return;
      updateSummary(summary.rows);
      renderTable(
        $('overview-balances'),
        accounts.rows.slice(0, 8),
        'Your ledger starts here',
        'Create an account, then record your first posting.'
      );
      renderTable(
        $('overview-reorder'),
        reorder.rows,
        'Stock levels are in balance',
        'No items are currently at their reorder threshold.'
      );
    } else if (currentView === 'compose') {
      await api('/api/health');
    } else {
      const result = await report(reportCommand());
      if (generation !== state.generation) return;
      state.rows = result.rows;
      filteredTable();
      $('report-message').textContent = result.message;
    }
    connection(true);
  } catch (error) {
    if (generation !== state.generation) return;
    connection(false);
    notify(error.message, true);
    if (currentView === 'overview') {
      ['metric-entries', 'metric-items', 'metric-invoices', 'metric-result'].forEach((id) => {
        $(id).textContent = '—';
      });
      makeEmpty(
        $('overview-balances'),
        'Workspace unavailable',
        'Check your connection and try refreshing.'
      );
      makeEmpty(
        $('overview-reorder'),
        'Report unavailable',
        'Connect to the engine to read inventory levels.'
      );
    } else if (currentView !== 'compose') {
      state.rows = [];
      makeEmpty($('report-table'), 'Report unavailable', error.message);
      $('row-count').textContent = 'Unable to load report';
    }
  } finally {
    if (generation === state.generation) $('refresh-button').disabled = false;
  }
}
export function navigate(view) {
  if (!views[view]) return;
  state.view = view;
  document
    .querySelectorAll('[data-view]')
    .forEach((button) => button.classList.toggle('active', button.dataset.view === view));
  $('page-title').textContent = views[view][0];
  $('page-description').textContent = views[view][1];
  $('breadcrumb-view').textContent = views[view][2];
  $('page-eyebrow').textContent =
    view === 'overview' ? 'YOUR BUSINESS, IN BALANCE' : 'MERIDIAN WORKSPACE';
  $('overview-view').hidden = view !== 'overview';
  $('compose-view').hidden = view !== 'compose';
  $('data-view').hidden = ['overview', 'compose'].includes(view);
  $('new-transaction').hidden = view === 'compose';
  $('sidebar').classList.remove('open');
  $('menu-button').setAttribute('aria-expanded', 'false');
  $('notice').hidden = true;
  if (views[view][3]) {
    $('report-select').replaceChildren();
    views[view][3].forEach((name) => {
      const option = document.createElement('option');
      option.value = name;
      option.textContent = reportNames[name];
      $('report-select').append(option);
    });
    configureReport();
    makeEmpty($('report-table'), 'Reading the journal', 'Loading current workspace records…');
  }
  refresh();
}

export function initNavigation() {
  document
    .querySelectorAll('[data-view]')
    .forEach((button) => button.addEventListener('click', () => navigate(button.dataset.view)));
  document
    .querySelectorAll('[data-go]')
    .forEach((button) => button.addEventListener('click', () => navigate(button.dataset.go)));
  $('new-transaction').addEventListener('click', () => navigate('compose'));
  $('refresh-button').addEventListener('click', refresh);
  $('menu-button').addEventListener('click', () => {
    const open = $('sidebar').classList.toggle('open');
    $('menu-button').setAttribute('aria-expanded', String(open));
  });
  $('report-select').addEventListener('change', () => {
    configureReport();
    refresh();
  });
  $('run-report').addEventListener('click', refresh);
  $('report-argument').addEventListener('keydown', (event) => {
    if (event.key === 'Enter') refresh();
  });
  $('table-search').addEventListener('input', filteredTable);
  $('export-button').addEventListener('click', exportCSV);
}
