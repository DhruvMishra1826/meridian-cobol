'use strict';

const $ = (id) => document.getElementById(id);
const state = {
  view: 'overview',
  token: '',
  rows: [],
  report: 'ACCOUNTS',
  generation: 0,
  busy: false,
};
const today = () => {
  const d = new Date();
  return [
    d.getFullYear(),
    String(d.getMonth() + 1).padStart(2, '0'),
    String(d.getDate()).padStart(2, '0'),
  ].join('');
};
const integer = (value) =>
  /^-?\d+$/.test(String(value)) ? Number(value).toLocaleString('en-US') : value;
const date = (value) =>
  /^\d{8}$/.test(value) ? `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6)}` : value;
const views = {
  overview: [
    'Operations overview',
    'A clear view of your ledger, inventory and receivables.',
    'Overview',
  ],
  accounts: [
    'General ledger',
    'Balanced postings, traceable references and period controls.',
    'General ledger',
    ['ACCOUNTS', 'TRIAL', 'JOURNAL', 'STATEMENT'],
  ],
  inventory: [
    'Inventory',
    'Track standard-cost stock, movements and replenishment needs.',
    'Inventory',
    ['STOCK', 'MOVEMENTS', 'REORDER'],
  ],
  customers: [
    'Customer directory',
    'Maintain the customers behind your receivables.',
    'Customers',
    ['CUSTOMERS'],
  ],
  invoices: [
    'Invoicing',
    'From draft line items to issued invoices and recorded payments.',
    'Invoices',
    ['INVOICES', 'INVOICE-SHOW', 'AGING'],
  ],
  reports: [
    'Reports & controls',
    'Read current balances and journal activity from your workspace.',
    'Reports',
    [
      'SUMMARY',
      'TRIAL',
      'JOURNAL',
      'STATEMENT',
      'STOCK',
      'MOVEMENTS',
      'REORDER',
      'AGING',
      'INVOICE-SHOW',
      'ACCOUNTS',
      'CUSTOMERS',
      'INVOICES',
    ],
  ],
  compose: [
    'Transaction desk',
    'Compose a validated operation and commit it to your journal.',
    'Transaction desk',
  ],
};
const reportNames = {
  ACCOUNTS: 'Account balances',
  TRIAL: 'Trial balance',
  JOURNAL: 'Journal entries',
  STATEMENT: 'Account statement',
  SUMMARY: 'Workspace summary',
  STOCK: 'Stock on hand',
  MOVEMENTS: 'Stock movements',
  REORDER: 'Reorder report',
  CUSTOMERS: 'Customers',
  INVOICES: 'Invoices',
  'INVOICE-SHOW': 'Invoice detail',
  AGING: 'Receivables aging',
};
const schemas = {
  ACCOUNT: ['Account ID', 'Type', 'Account name', 'Balance'],
  ENTRY: ['Reference', 'Date', 'Debit account', 'Credit account', 'Amount', 'Memo', 'Reversed by'],
  TRIAL: ['Account ID', 'Account name', 'Debits', 'Credits'],
  TOTAL: ['Total debits', 'Total credits'],
  BALANCE: ['Account ID', 'Balance'],
  SUMMARY: ['Account class', 'Balance'],
  RESULT: ['Net result'],
  PERIOD: ['Closed through'],
  COUNTS: ['Accounts', 'Ledger entries', 'Items', 'Customers', 'Invoices'],
  STOCK: ['SKU', 'Item name', 'Quantity', 'Unit cost', 'Stock value', 'Reorder point'],
  MOVEMENT: ['Reference', 'Date', 'SKU', 'Quantity change', 'Memo'],
  REORDER: ['SKU', 'Item name', 'Quantity', 'Reorder point', 'Shortfall'],
  CUSTOMER: ['Customer ID', 'Name', 'Email'],
  INVOICE: [
    'Invoice ID',
    'Customer ID',
    'Date',
    'Due date',
    'Status',
    'Net',
    'Tax',
    'Total',
    'Paid',
    'Outstanding',
    'Lines',
  ],
  LINE: ['Line', 'SKU', 'Quantity', 'Unit price', 'Tax basis points', 'Net', 'Tax'],
  PAYMENT: ['Reference', 'Date', 'Amount'],
  AGE: ['Customer ID', 'Invoice ID', 'Due date', 'Overdue days', 'Bucket', 'Outstanding'],
  'AGE-TOTAL': [
    'Current',
    '1–30 days',
    '31–60 days',
    '61–90 days',
    'Over 90 days',
    'Open invoices',
  ],
};
const field = (label, value = '', hint = '', kind = 'text') => ({ label, value, hint, kind });
const operations = [
  {
    name: 'ACCOUNT',
    label: 'Create ledger account',
    hint: 'Register an account before posting. Choose ASSET, LIABILITY, EQUITY, REVENUE or EXPENSE.',
    fields: [
      field('Account ID', 'CASH', 'Uppercase unique identifier', 'id'),
      field('Account type', 'ASSET', 'ASSET / LIABILITY / EQUITY / REVENUE / EXPENSE'),
      field('Account name', 'Operating cash'),
    ],
  },
  {
    name: 'POST',
    label: 'Post journal entry',
    hint: 'Record one balanced debit and credit. Amount must be positive and the reference unique.',
    fields: [
      field('Reference', 'OPENING_001', 'Unique posting reference', 'id'),
      field('Posting date', today(), 'YYYYMMDD', 'date'),
      field('Debit account', 'CASH', 'Existing account', 'id'),
      field('Credit account', 'EQUITY', 'Existing account', 'id'),
      field('Amount', '100000', 'Integer minor units', 'uint'),
      field('Memo', 'Opening capital'),
    ],
  },
  {
    name: 'REVERSE',
    label: 'Reverse journal entry',
    hint: 'Create a balancing entry for an existing posting using a fresh reference.',
    fields: [
      field('Original reference', 'OPENING_001', 'Existing entry reference', 'id'),
      field('New reference', 'REV_OPENING_001', 'Unique reversal reference', 'id'),
      field('Posting date', today(), 'YYYYMMDD', 'date'),
      field('Memo', 'Correct opening entry'),
    ],
  },
  {
    name: 'CLOSE',
    label: 'Close accounting period',
    hint: 'Posting dates on or before this date will be rejected. Review the ledger before closing.',
    fields: [field('Closed-through date', today(), 'YYYYMMDD', 'date')],
  },
  {
    name: 'ITEM',
    label: 'Register inventory item',
    hint: 'Create a stock item with a fixed standard cost and a replenishment threshold.',
    fields: [
      field('SKU', 'WIDGET', 'Unique stock identifier', 'id'),
      field('Item name', 'Industrial widget'),
      field('Standard cost', '2500', 'Integer minor units per unit', 'uint'),
      field('Reorder point', '10', 'Integer units', 'uint'),
    ],
  },
  {
    name: 'RECEIVE',
    label: 'Receive inventory',
    hint: 'Increase stock and post the standard-cost value to inventory and an offset account.',
    fields: [
      field('Reference', 'RECEIPT_001', 'Unique receipt reference', 'id'),
      field('Receipt date', today(), 'YYYYMMDD', 'date'),
      field('SKU', 'WIDGET', 'Existing stock item', 'id'),
      field('Quantity', '100', 'Integer units', 'uint'),
      field('Inventory account', 'INVENTORY', 'Existing asset account', 'id'),
      field('Offset account', 'AP', 'Existing offset account', 'id'),
      field('Memo', 'Supplier delivery'),
    ],
  },
  {
    name: 'ADJUST',
    label: 'Adjust inventory',
    hint: 'Apply a signed stock correction and post its value. Negative quantities reduce stock.',
    fields: [
      field('Reference', 'ADJUST_001', 'Unique adjustment reference', 'id'),
      field('Adjustment date', today(), 'YYYYMMDD', 'date'),
      field('SKU', 'WIDGET', 'Existing stock item', 'id'),
      field('Quantity change', '-2', 'Signed nonzero integer', 'signed'),
      field('Inventory account', 'INVENTORY', 'Existing asset account', 'id'),
      field('Adjustment account', 'ADJUSTMENT', 'Existing adjustment account', 'id'),
      field('Memo', 'Cycle count correction'),
    ],
  },
  {
    name: 'CUSTOMER',
    label: 'Create customer',
    hint: 'Register a customer before creating invoices.',
    fields: [
      field('Customer ID', 'ACME', 'Unique customer identifier', 'id'),
      field('Customer name', 'Acme Manufacturing'),
      field('Email', 'accounts@example.com'),
    ],
  },
  {
    name: 'INVOICE',
    label: 'Create draft invoice',
    hint: 'Create a draft document, then add lines before issuing it.',
    fields: [
      field('Invoice ID', 'INV_001', 'Unique invoice identifier', 'id'),
      field('Customer ID', 'ACME', 'Existing customer', 'id'),
      field('Invoice date', today(), 'YYYYMMDD', 'date'),
      field('Due date', today(), 'YYYYMMDD; on or after invoice date', 'date'),
    ],
  },
  {
    name: 'LINE',
    label: 'Add invoice line',
    hint: 'Add an item, quantity, selling price and tax rate to a draft invoice.',
    fields: [
      field('Invoice ID', 'INV_001', 'Existing draft invoice', 'id'),
      field('SKU', 'WIDGET', 'Existing stock item', 'id'),
      field('Quantity', '2', 'Integer units', 'uint'),
      field('Unit price', '4500', 'Integer minor units', 'uint'),
      field('Tax basis points', '1000', '1000 = 10%; 0 = no tax', 'uint'),
    ],
  },
  {
    name: 'ISSUE',
    label: 'Issue invoice',
    hint: 'Validate stock and post receivables, revenue, tax and cost of goods as one operation.',
    fields: [
      field('Invoice ID', 'INV_001', 'Existing draft invoice', 'id'),
      field('Receivables account', 'AR', 'Existing account', 'id'),
      field('Revenue account', 'SALES', 'Existing account', 'id'),
      field('Tax account', 'TAX', 'Existing account', 'id'),
      field('Cost of goods account', 'COGS', 'Existing account', 'id'),
      field('Inventory account', 'INVENTORY', 'Existing account', 'id'),
    ],
  },
  {
    name: 'PAY',
    label: 'Record invoice payment',
    hint: 'Apply payment to an open invoice. The engine rejects duplicate references and overpayment.',
    fields: [
      field('Payment reference', 'PAY_001', 'Unique payment reference', 'id'),
      field('Invoice ID', 'INV_001', 'Existing open invoice', 'id'),
      field('Payment date', today(), 'YYYYMMDD', 'date'),
      field('Amount', '9900', 'Integer minor units', 'uint'),
      field('Cash account', 'CASH', 'Existing account', 'id'),
      field('Receivables account', 'AR', 'Existing account', 'id'),
    ],
  },
  {
    name: 'VOID',
    label: 'Void draft invoice',
    hint: 'Void an unissued draft. Issued invoices cannot be voided with this operation.',
    fields: [field('Invoice ID', 'INV_001', 'Existing draft invoice', 'id')],
  },
];

function notify(message, error = false) {
  $('notice').hidden = false;
  $('notice').textContent = message;
  $('notice').classList.toggle('error', error);
}
function connection(ok) {
  $('engine-dot').classList.toggle('connected', ok);
  $('sidebar-status').textContent = ok ? 'Journal ready' : 'Connection unavailable';
  $('status-chip').textContent = ok ? 'Engine connected' : 'Connection unavailable';
}
async function api(path, command) {
  const options = { headers: {} };
  if (state.token) options.headers.Authorization = `Bearer ${state.token}`;
  if (command !== undefined) {
    options.method = 'POST';
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify({ command });
  }
  const response = await fetch(path, options);
  const result = await response.json();
  if (!response.ok || !result.ok) {
    if (response.status === 401 && !$('connection-dialog').open) $('connection-dialog').showModal();
    throw new Error(result.message || `Request failed (${response.status})`);
  }
  return result;
}
const report = (command) => api(`/api/report?command=${encodeURIComponent(command)}`);

function makeEmpty(target, title, description) {
  target.replaceChildren();
  const box = document.createElement('div');
  box.className = 'empty-state';
  const icon = document.createElement('span');
  icon.className = 'empty-icon';
  icon.textContent = '◫';
  const heading = document.createElement('strong');
  heading.textContent = title;
  const detail = document.createElement('span');
  detail.textContent = description;
  box.append(icon, heading, detail);
  target.append(box);
}
function renderTable(
  target,
  rows,
  emptyTitle = 'No records yet',
  emptyDescription = 'Create your first record in the transaction desk.'
) {
  target.replaceChildren();
  if (!rows.length) {
    makeEmpty(target, emptyTitle, emptyDescription);
    return;
  }
  const groups = new Map();
  rows.forEach((row) => {
    const kind = row[0];
    if (!groups.has(kind)) groups.set(kind, []);
    groups.get(kind).push(row);
  });
  groups.forEach((entries, kind) => {
    if (groups.size > 1) {
      const caption = document.createElement('p');
      caption.className = 'row-group-label';
      caption.textContent = kind.replace(/-/g, ' ');
      target.append(caption);
    }
    const table = document.createElement('table');
    const known = schemas[kind];
    const width = Math.max(...entries.map((row) => row.length - 1));
    const headers = known || Array.from({ length: width }, (_, index) => `Field ${index + 1}`);
    const head = document.createElement('thead');
    const hr = document.createElement('tr');
    headers.forEach((label) => {
      const th = document.createElement('th');
      th.scope = 'col';
      th.textContent = label;
      hr.append(th);
    });
    head.append(hr);
    table.append(head);
    const body = document.createElement('tbody');
    entries.forEach((row) => {
      const tr = document.createElement('tr');
      row.slice(1).forEach((value, index) => {
        const td = document.createElement('td');
        const label = headers[index] || '';
        td.title = value;
        if (label === 'Status' || label === 'Type' || label === 'Bucket') {
          const badge = document.createElement('span');
          badge.className = 'badge';
          if (['OPEN', 'PAID', 'VOID', 'DRAFT'].includes(value)) badge.classList.add(value);
          badge.textContent = value;
          td.append(badge);
        } else if (/date|Closed through/i.test(label)) {
          td.textContent = value === '00000000' || value === '0' ? 'Not closed' : date(value);
        } else if (
          /balance|amount|debits|credits|quantity|cost|value|point|shortfall|price|basis|^net$|^tax$|^total$|^paid$|outstanding|lines|^line$|days|result|^current$|^accounts$|^items$|^customers$|^invoices$|^ledger entries$/i.test(
            label
          )
        ) {
          td.className = 'number';
          td.textContent = integer(value);
        } else {
          td.textContent = value || '—';
          if (/ID|SKU|reference|account$/i.test(label)) td.className = 'identifier';
          if (/name/i.test(label)) td.className = 'name';
        }
        tr.append(td);
      });
      body.append(tr);
    });
    table.append(body);
    target.append(table);
  });
}
function updateSummary(rows) {
  const counts = rows.find((row) => row[0] === 'COUNTS');
  const result = rows.find((row) => row[0] === 'RESULT');
  $('metric-entries').textContent = counts ? integer(counts[2]) : '—';
  $('metric-items').textContent = counts ? integer(counts[3]) : '—';
  $('metric-invoices').textContent = counts ? integer(counts[5]) : '—';
  $('metric-result').textContent = result ? integer(result[1]) : '—';
}
function filteredTable() {
  const filter = $('table-search').value.toLowerCase();
  const rows = state.rows.filter((row) =>
    row.some((value) => value.toLowerCase().includes(filter))
  );
  renderTable(
    $('report-table'),
    rows,
    filter ? 'No matching records' : 'No records yet',
    filter ? 'Try another search term.' : 'Accepted operations will appear here.'
  );
  $('row-count').textContent = `${rows.length} of ${state.rows.length} report rows`;
}
function reportCommand() {
  const name = $('report-select').value;
  return ['STATEMENT', 'INVOICE-SHOW', 'AGING'].includes(name)
    ? `${name}|${$('report-argument').value}`
    : name;
}
function configureReport() {
  const name = $('report-select').value;
  state.report = name;
  $('table-title').textContent = reportNames[name];
  const hasArgument = ['STATEMENT', 'INVOICE-SHOW', 'AGING'].includes(name);
  $('report-argument-wrap').hidden = !hasArgument;
  $('report-argument-label').textContent =
    name === 'AGING' ? 'As-of date' : name === 'STATEMENT' ? 'Account ID' : 'Invoice ID';
  $('report-argument').value =
    name === 'AGING' ? today() : name === 'STATEMENT' ? 'CASH' : 'INV_001';
  $('table-search').value = '';
}
async function refresh() {
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
function navigate(view) {
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
function composeOperation() {
  const operation = operations.find((op) => op.name === $('operation-select').value);
  $('operation-hint').textContent = operation.hint;
  $('command-fields').replaceChildren();
  operation.fields.forEach((spec, index) => {
    const wrapper = document.createElement('div');
    wrapper.className = 'field';
    const label = document.createElement('label');
    label.htmlFor = `command-field-${index}`;
    label.textContent = spec.label;
    const input = document.createElement('input');
    input.id = label.htmlFor;
    input.value = spec.value;
    input.required = true;
    input.autocomplete = 'off';
    input.maxLength = 80;
    input.dataset.kind = spec.kind;
    if (spec.kind === 'id') {
      input.pattern = '[A-Z0-9_\\-]+';
      input.maxLength = /Invoice ID/.test(spec.label)
        ? 24
        : /reference/i.test(spec.label)
          ? 32
          : 12;
    }
    if (spec.kind === 'date') {
      input.pattern = '[0-9]{8}';
      input.inputMode = 'numeric';
      input.maxLength = 8;
    }
    if (spec.kind === 'uint') {
      input.pattern = '(0|[1-9][0-9]*)';
      input.inputMode = 'numeric';
    }
    if (spec.kind === 'signed') {
      input.pattern = '-?[1-9][0-9]*';
      input.inputMode = 'text';
    }
    if (spec.kind === 'text') input.pattern = '[^\\x7c\\x7e\\x00-\\x1f\\x7f]+';
    input.addEventListener('input', previewCommand);
    const hint = document.createElement('small');
    hint.textContent = spec.hint || 'No pipe, tilde or control characters';
    wrapper.append(label, input, hint);
    $('command-fields').append(wrapper);
  });
  previewCommand();
}
function previewCommand() {
  const values = Array.from($('command-fields').querySelectorAll('input'), (input) => input.value);
  const command = [$('operation-select').value, ...values].join('|');
  $('command-preview').textContent = command;
  return command;
}
function exportCSV() {
  if (!state.rows.length) {
    notify('There are no report rows to export.');
    return;
  }
  // Prefix spreadsheet formula markers while preserving values in the on-screen report.
  const escape = (value) =>
    `"${(/^[=+@-]/.test(value) && !/^-?\d+$/.test(value) ? "'" + value : value).replace(/"/g, '""')}"`;
  const csv = state.rows.map((row) => row.map(escape).join(',')).join('\r\n') + '\r\n';
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = `meridian-${state.report.toLowerCase()}-${today()}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}

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
$('connection-button').addEventListener('click', () => $('connection-dialog').showModal());
$('close-connection').addEventListener('click', () => $('connection-dialog').close());
$('connection-form').addEventListener('submit', (event) => {
  event.preventDefault();
  state.token = $('token-input').value;
  $('token-input').value = '';
  $('connection-dialog').close();
  $('notice').hidden = true;
  refresh();
});
operations.forEach((operation) => {
  const option = document.createElement('option');
  option.value = operation.name;
  option.textContent = operation.label;
  $('operation-select').append(option);
});
$('operation-select').addEventListener('change', composeOperation);
$('command-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (state.busy) return;
  const command = previewCommand();
  if (new TextEncoder().encode(command).length > 4096 || /[\x00-\x1f\x7f~]/.test(command)) {
    notify(
      'Fields must fit within 4096 bytes and cannot contain tilde or control characters.',
      true
    );
    return;
  }
  if (
    Array.from($('command-fields').querySelectorAll('input')).some((input) =>
      input.value.includes('|')
    )
  ) {
    notify('A field cannot contain a pipe character.', true);
    return;
  }
  state.busy = true;
  $('submit-command').disabled = true;
  try {
    const result = await api('/api/command', command);
    connection(true);
    notify(`${result.message}. Accepted into the journal.`);
  } catch (error) {
    notify(error.message, true);
  } finally {
    state.busy = false;
    $('submit-command').disabled = false;
  }
});
composeOperation();
navigate('overview');
