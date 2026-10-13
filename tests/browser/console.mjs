import assert from 'node:assert/strict';
import { execFileSync, spawn } from 'node:child_process';
import { once } from 'node:events';
import { access, mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { createInterface } from 'node:readline';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const python = process.env.MERIDIAN_PYTHON || 'python3';

async function startServer(dataDir) {
    const server = spawn(python, ['-m', 'tools.server', '--data-dir', dataDir, '--port', '0'], {
        cwd: root,
        env: { ...process.env, MERIDIAN_API_TOKEN: '' },
        stdio: ['ignore', 'pipe', 'pipe'],
    });
    let errors = '';
    server.stderr.on('data', (chunk) => {
        errors = (errors + chunk).slice(-16000);
    });
    const lines = createInterface({ input: server.stdout });
    const url = await new Promise((resolveURL, reject) => {
        const timer = setTimeout(() => {
            server.kill();
            reject(new Error(`Server startup timed out: ${errors}`));
        }, 10000);
        server.once('error', (error) => {
            clearTimeout(timer);
            reject(error);
        });
        server.once('exit', (code) => {
            clearTimeout(timer);
            reject(new Error(`Server exited during startup (${code}): ${errors}`));
        });
        lines.on('line', (line) => {
            if (line.startsWith('Meridian console: ')) {
                clearTimeout(timer);
                resolveURL(line.slice('Meridian console: '.length));
            }
        });
    });
    return { server, url, lines };
}

async function navigate(page, view) {
    await page.locator(`[data-view="${view}"]`).click();
    await page.waitForFunction(() => !document.getElementById('refresh-button').disabled);
}

async function record(page, operation, values) {
    await page.locator('#operation-select').selectOption(operation);
    const fields = page.locator('#command-fields input');
    assert.equal(await fields.count(), values.length);
    for (let index = 0; index < values.length; index++) {
        await fields.nth(index).fill(values[index]);
    }
    const response = page.waitForResponse((item) => item.url().endsWith('/api/command'));
    await page.locator('#submit-command').click();
    const result = await (await response).json();
    assert.equal(result.ok, true, result.message);
    await page.waitForFunction(() => !document.getElementById('submit-command').disabled);
    assert.equal(await page.locator('#notice').getAttribute('class'), 'notice');
}

async function runReport(page, command) {
    const [name, argument] = command.split('|');
    await page.locator('#report-select').selectOption(name);
    if (argument) {
        await page.locator('#report-argument').fill(argument);
        await page.locator('#run-report').click();
    }
    await page.waitForFunction(() => !document.getElementById('refresh-button').disabled);
    assert.match(await page.locator('#row-count').textContent(), /\d+ of \d+ report rows/);
    assert.equal(await page.locator('#status-chip').textContent(), 'Engine connected');
}

test('browser console integrates with the real COBOL engine', { timeout: 120000 }, async (t) => {
    await access(join(root, 'build/meridian'));
    const temporary = await mkdtemp(join(tmpdir(), 'meridian-browser-'));
    const dataDir = join(temporary, 'ledger');
    let browser;
    let service;
    try {
        execFileSync(python, ['-m', 'tools.demo', '--data-dir', dataDir], {
            cwd: root,
            stdio: 'pipe',
        });
        service = await startServer(dataDir);
        const launchOptions = { headless: true };
        if (process.env.MERIDIAN_BROWSER_EXECUTABLE) {
            launchOptions.executablePath = process.env.MERIDIAN_BROWSER_EXECUTABLE;
        }
        browser = await chromium.launch(launchOptions);
        const context = await browser.newContext({
            viewport: { width: 1440, height: 960 },
            acceptDownloads: true,
        });
        const page = await context.newPage();
        const errors = [];
        page.on('pageerror', (error) => errors.push(error.message));
        await page.goto(service.url);
        await page.waitForFunction(
            () => document.getElementById('status-chip').textContent === 'Engine connected'
        );

        await t.test('ES modules load and overview shows reconciled demo metrics', async () => {
            assert.equal(await page.locator('#metric-entries').textContent(), '10');
            assert.equal(await page.locator('#metric-items').textContent(), '2');
            assert.equal(await page.locator('#metric-invoices').textContent(), '2');
            for (const module of [
                'api',
                'catalog',
                'dom',
                'forms',
                'navigation',
                'operations',
                'reports',
                'state',
            ]) {
                const response = await context.request.get(`${service.url}/${module}.js`);
                assert.equal(response.status(), 200, `${module}.js must be served`);
                assert.match(response.headers()['content-type'], /javascript/);
            }
        });

        const htmlName = '<img src=x onerror="window.injected=1">';
        await t.test('forms create, issue and settle an invoice atomically', async () => {
            await navigate(page, 'compose');
            await record(page, 'CUSTOMER', ['BROWSER', htmlName, 'browser@example.com']);
            await record(page, 'CUSTOMER', ['FORMULA', '=1+1', 'formula@example.com']);
            await record(page, 'INVOICE', ['INV_001', 'ACME', '20261015', '20261115']);
            await record(page, 'INVOICE', ['BROWSER', 'BROWSER', '20261015', '20261115']);
            await record(page, 'LINE', ['BROWSER', 'WIDGET', '2', '2000', '1000']);
            await record(page, 'ISSUE', ['BROWSER', 'AR', 'SALES', 'TAX', 'COGS', 'INVENTORY']);
            await record(page, 'PAY', ['PAY_BROWSER', 'BROWSER', '20261015', '4400', 'CASH', 'AR']);
            await navigate(page, 'invoices');
            const row = page.locator('#report-table tbody tr').filter({ hasText: 'BROWSER' });
            assert.match(await row.textContent(), /PAID/);
            assert.equal(await row.locator('td').nth(9).textContent(), '0');
        });

        await t.test('all twelve reports render with their required arguments', async () => {
            await navigate(page, 'reports');
            for (const command of [
                'SUMMARY',
                'TRIAL',
                'JOURNAL',
                'STATEMENT|CASH',
                'STOCK',
                'MOVEMENTS',
                'REORDER',
                'AGING|20261116',
                'INVOICE-SHOW|BROWSER',
                'ACCOUNTS',
                'CUSTOMERS',
                'INVOICES',
            ]) {
                await runReport(page, command);
            }
            await runReport(page, 'INVOICE-SHOW|BROWSER');
            assert.match(await page.locator('#report-table').textContent(), /PAY_BROWSER/);
        });

        await t.test('search, literal HTML rendering and spreadsheet-safe CSV export', async () => {
            await runReport(page, 'CUSTOMERS');
            assert.match(await page.locator('#report-table').textContent(), /<img src=x/);
            assert.equal(await page.locator('#report-table img').count(), 0);
            assert.equal(await page.evaluate(() => window.injected), undefined);
            await page.locator('#table-search').fill('browser');
            assert.equal(await page.locator('#report-table tbody tr').count(), 1);
            await page.locator('#table-search').fill('no-such-record');
            assert.match(await page.locator('#report-table').textContent(), /No matching records/);
            await page.locator('#table-search').fill('');
            const download = page.waitForEvent('download');
            await page.locator('#export-button').click();
            const file = await download;
            const csv = await readFile(await file.path(), 'utf8');
            assert.match(csv, /"'=1\+1"/);
            assert.match(csv, /<img src=x onerror=""window.injected=1"">/);
        });

        await t.test(
            '390px navigation and report tables stay within the mobile viewport',
            async () => {
                const mobile = await context.newPage();
                await mobile.setViewportSize({ width: 390, height: 844 });
                mobile.on('pageerror', (error) => errors.push(error.message));
                await mobile.goto(service.url);
                await mobile.waitForFunction(
                    () => document.getElementById('status-chip').textContent === 'Engine connected'
                );
                await mobile.locator('#menu-button').click();
                assert.equal(
                    await mobile.locator('#menu-button').getAttribute('aria-expanded'),
                    'true'
                );
                await navigate(mobile, 'inventory');
                assert.equal(
                    await mobile.locator('#menu-button').getAttribute('aria-expanded'),
                    'false'
                );
                assert.match(await mobile.locator('#report-table').textContent(), /WIDGET/);
                const dimensions = await mobile.evaluate(() => ({
                    scroll: document.documentElement.scrollWidth,
                    viewport: innerWidth,
                }));
                assert.ok(dimensions.scroll <= dimensions.viewport, JSON.stringify(dimensions));
                await mobile.close();
            }
        );
        assert.deepEqual(errors, [], 'Browser runtime must not report uncaught errors');
        await context.close();
    } finally {
        if (browser) await browser.close();
        if (service) {
            if (service.server.exitCode === null && service.server.signalCode === null) {
                const exit = once(service.server, 'exit');
                service.server.kill('SIGTERM');
                await exit;
            }
            service.lines.close();
        }
        await rm(temporary, { recursive: true, force: true });
    }
});
