// End-to-end UI test of R07/R09 against the local stack. Usage: node e2e.mjs <memberEmail> <memberPw> <modEmail> <modPw>
import puppeteer from 'puppeteer-core';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

const [MEMBER, MEMBER_PW, MOD, MOD_PW] = process.argv.slice(2);
const HERE = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'));
const SHOTS = path.join(HERE, 'shots'); // screenshots, git-ignored
fs.mkdirSync(SHOTS, { recursive: true });
const TOTP_SECRET = (process.env.TOTP_SECRET || '').trim();
const WEB = 'http://localhost:5173';
const STAFF = 'http://localhost:5174';
const API = 'http://localhost:8000';
const STAMP = Date.now().toString(36);

const results = [];
const ok = (id, name, cond, detail = '') => {
  results.push({ id, name, pass: Boolean(cond), detail: String(detail).slice(0, 200) });
  console.log(`${cond ? 'PASS' : 'FAIL'}  ${id}  ${name}${cond ? '' : '  -> ' + String(detail).slice(0, 200)}`);
};

function base32(s) { const A = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'; let bits = ''; for (const c of s.replace(/=+$/, '').toUpperCase()) bits += A.indexOf(c).toString(2).padStart(5, '0'); const out = []; for (let i = 0; i + 8 <= bits.length; i += 8) out.push(parseInt(bits.slice(i, i + 8), 2)); return Buffer.from(out); }
function totp() { const c = Buffer.alloc(8); c.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30000))); const h = crypto.createHmac('sha1', base32(TOTP_SECRET)).update(c).digest(); const o = h[19] & 15; return String(((h.readUInt32BE(o) & 0x7fffffff) % 1e6)).padStart(6, '0'); }

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const browser = await puppeteer.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: 'new', protocolTimeout: 120000, args: ['--no-sandbox', '--window-size=1280,900'] });

async function newPage(ctx, { lang = 'en', width = 1280, height = 900 } = {}) {
  const page = await ctx.newPage();
  await page.setViewport({ width, height });
  await page.evaluateOnNewDocument((l) => { try { localStorage.setItem('abhijatri_lang', l); } catch {} }, lang);
  // The live notification stream holds one of Chrome's 6 connections per host per tab; these tests do not need it.
  await page.setRequestInterception(true);
  page.on('request', (r) => { if (r.isInterceptResolutionHandled()) return; if (r.url().includes('/notifications/stream')) r.abort(); else r.continue(); });
  { const orig = page.goto.bind(page); page.goto = async (...a) => { await page.bringToFront(); return orig(...a); }; }
  page.on('pageerror', (e) => console.log('   [pageerror]', String(e).slice(0, 160)));
  return page;
}
async function shot(page, name) { await page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage: true }); }
async function setValue(page, sel, text) { await page.bringToFront(); await page.waitForSelector(sel, { timeout: 15000 }); await page.click(sel, { clickCount: 3 }); await page.keyboard.press('Backspace'); if (text) await page.type(sel, text); }
async function clickText(page, tag, re, opts = {}) {
  await page.bringToFront();
  const h = await page.evaluateHandle((tag, src, flags) => { const r = new RegExp(src, flags); return [...document.querySelectorAll(tag)].find((el) => r.test((el.innerText || el.textContent || '').trim()) && !el.disabled); }, tag, re.source, re.flags);
  const el = h.asElement(); if (!el) throw new Error(`no ${tag} matching ${re}`); await el.click(); return el;
}
const hasText = async (page, re) => page.evaluate((src, f) => new RegExp(src, f).test(document.body.innerText), re.source, re.flags);
async function waitText(page, re, timeout = 15000) { await page.waitForFunction((src, f) => new RegExp(src, f).test(document.body.innerText), { timeout }, re.source, re.flags); }
async function waitCard(page, sel, re, timeout = 20000) { await page.waitForFunction((sel, src) => { const el = document.querySelector(sel); return el && new RegExp(src, 'i').test(el.innerText); }, { timeout }, sel, re.source); }
const textOf = (page, sel) => page.$eval(sel, (e) => e.innerText);

async function api(page, method, p, body) { // fetch from inside the signed-in page (cookie + CSRF), as the app does
  return page.evaluate(async (API, method, p, body) => {
    const csrf = method === 'GET' ? null : (await (await fetch(`${API}/api/v1/auth/csrf`, { credentials: 'include' })).json()).csrf_token;
    const r = await fetch(`${API}${p}`, { method, credentials: 'include', headers: { 'Content-Type': 'application/json', ...(csrf ? { 'X-CSRF-Token': csrf } : {}) }, body: body ? JSON.stringify(body) : undefined });
    let j = null; try { j = await r.json(); } catch {}
    return { status: r.status, json: j };
  }, API, method, p, body);
}

const dests = await (await fetch(`${API}/api/v1/destinations?limit=10`)).json();
const D1 = dests.items[0], D2 = dests.items[1];
const RUN = (() => { const f = path.join(HERE, '.run'); const n = (fs.existsSync(f) ? Number(fs.readFileSync(f, 'utf8')) : 0) + 1; fs.writeFileSync(f, String(n)); return n; })();
const monthsAgo = (n) => { const d = new Date(); d.setUTCDate(1); d.setUTCMonth(d.getUTCMonth() - n - RUN * 30); return d.toISOString().slice(0, 7); };

// =========================== staff helpers ===========================
const staffCtx = await browser.createBrowserContext();
const staff = await newPage(staffCtx);
async function staffLogin() {
  await staff.goto(STAFF, { waitUntil: 'domcontentloaded' });
  await setValue(staff, '#staff-email', MOD); await setValue(staff, '#staff-password', MOD_PW);
  await clickText(staff, 'button', /^Sign in/i).catch(async () => staff.keyboard.press('Enter'));
  await staff.waitForSelector('#totp-code', { timeout: 20000 });
  await setValue(staff, '#totp-code', totp());
  await staff.keyboard.press('Enter');
  await staff.waitForFunction(() => /Queue|Sections|Sign out/i.test(document.body.innerText) && !document.querySelector('#totp-code'), { timeout: 20000 });
}
async function staffDecide(titleRe, decision, reasonValue) {
  await clickText(staff, 'button', /Refresh|Reload/i).catch(() => {});
  await sleep(1200);
  const item = await staff.evaluateHandle((src) => [...document.querySelectorAll('button.item')].find((b) => new RegExp(src, 'i').test(b.innerText)), titleRe.source);
  if (!item.asElement()) throw new Error('queue item not found: ' + titleRe);
  await item.asElement().click();
  await clickText(staff, 'button', /Claim this task/i);
  await staff.waitForSelector('fieldset.decision', { timeout: 15000 });
  const opts = await staff.$$eval('fieldset.decision .segmented button', (bs) => bs.map((b) => b.innerText.trim()));
  await clickText(staff, 'fieldset.decision .segmented button', new RegExp(`^${decision}$`, 'i'));
  if (reasonValue) await staff.select('#reason-code', reasonValue);
  await shot(staff, `staff-${decision.replace(/\W+/g, '_')}`);
  await clickText(staff, 'button', /Submit decision/i);
  await waitText(staff, /Done:|Fertig|সম্পন্ন/i, 15000);
  return opts;
}

try {
  // ============================== 1. member sign-in ==============================
  const mctx = await browser.createBrowserContext();
  const m = await newPage(mctx);
  await m.goto(`${WEB}/login`, { waitUntil: 'domcontentloaded' });
  await setValue(m, '#signin-email', MEMBER); await setValue(m, '#signin-password', MEMBER_PW);
  await m.click('button[type=submit]');
  await m.waitForFunction(() => !location.pathname.startsWith('/login'), { timeout: 20000 }).catch(() => {});
  await sleep(1500);
  const signedIn = await m.evaluate(async (API) => (await (await fetch(`${API}/api/v1/auth/session`, { credentials: 'include' })).json()).authenticated, API);
  ok('S1', 'member signs in through the sign-in page', signedIn === true);

  // ============================== 2. create a member review via the form ==============================
  const T1 = `UI test A ${STAMP}`;
  await m.goto(`${WEB}/reviews?destination=${D1.id}`, { waitUntil: 'domcontentloaded' });
  await m.waitForSelector('#review-title');
  await m.select('#review-destination', D1.id);
  await m.$eval('#review-month', (el, v) => { const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set; set.call(el, v); el.dispatchEvent(new Event('input', { bubbles: true })); }, monthsAgo(1));
  await m.click('[role=radio][aria-label="4 stars"]');
  await setValue(m, '#review-title', T1);
  await setValue(m, '#review-body', 'We watched the clouds roll over the hills at sunrise and it was lovely.');
  await m.click('input[type=checkbox]');
  await clickText(m, 'button', /Submit review/i);
  await m.waitForSelector('#receipt-heading', { timeout: 20000 });
  const rid = await m.$eval('dd.select-all', (e) => e.innerText.trim());
  ok('C1', 'member review is created and a receipt page is shown', /^[0-9a-f-]{36}$/.test(rid), rid);
  await shot(m, 'member-created');

  // ============================== 3. My reviews: list, chips, actions ==============================
  await m.goto(`${WEB}/account/reviews`, { waitUntil: 'domcontentloaded' });
  const card = `li[data-review-id="${rid}"]`;
  await waitCard(m, card, new RegExp(T1));
  ok('L1', 'My reviews lists the new review with a "Waiting for moderation" chip', await m.$eval(card, (e) => /Waiting for moderation/.test(e.innerText)));
  ok('L2', 'a pending review offers Edit and Withdraw (and no Appeal)', await m.$eval(card, (e) => /Edit/.test(e.innerText) && /Withdraw/.test(e.innerText) && !/Appeal/.test(e.innerText)));
  ok('L3', 'the status chip has text, not only colour', await m.$eval(`${card} [data-status]`, (e) => e.innerText.trim().length > 3));
  await shot(m, 'my-reviews-1');

  // ============================== 4. edit: only changed fields, new version ==============================
  await m.goto(`${WEB}/account/reviews/${rid}/edit`, { waitUntil: 'domcontentloaded' });
  await m.waitForSelector('#edit-title');
  ok('E1', 'edit form opens prefilled with the review', (await m.$eval('#edit-title', (e) => e.value)) === T1);
  ok('E2', 'Save is disabled until something changes', await m.$eval('button[type=submit]', (b) => b.disabled));
  await setValue(m, '#edit-body', 'short');
  await clickText(m, 'button', /^Save$/i).catch(() => {});
  ok('E3', 'a too-short note is refused on the page with an inline error', await hasText(m, /note must be|at least|20/i));
  await setValue(m, '#edit-body', 'We watched the clouds roll over the hills at sunrise and it was lovely.');
  await setValue(m, '#edit-title', `${T1} edited`);
  ok('E4', 'Save turns on after a change', !(await m.$eval('button[type=submit]', (b) => b.disabled)));
  let patchBody = null;
  m.on('request', (req) => { if (req.method() === 'PATCH' && req.url().includes('/pending')) patchBody = req.postData() });
  await clickText(m, 'button', /^Save$/i);
  await m.waitForFunction(() => /version 2/i.test(document.body.innerText), { timeout: 15000 }).catch(() => {});
  const sent = patchBody ? JSON.parse(patchBody) : {};
  ok('E5', 'the PATCH sent only the version and the changed title', JSON.stringify(Object.keys(sent).sort()) === JSON.stringify(['expected_version', 'title']), JSON.stringify(sent));
  ok('E6', 'after saving, the detail page shows "Saved as version 2" and two versions in the history', (await hasText(m, /Saved as version 2/i)) && (await m.$$eval('section[aria-label="Version history"] li', (l) => l.length)) === 2);
  await shot(m, 'detail-after-edit');

  // conflict: a second tab saves first, then the first tab saves with a stale version
  // Only two tabs of the app at once: every tab holds a live notification stream and Chrome allows 6 HTTP/1.1 connections per host.
  const a = await newPage(mctx);
  await a.goto(`${WEB}/account/reviews/${rid}/edit`, { waitUntil: 'domcontentloaded' }); await a.waitForSelector('#edit-title');
  await m.bringToFront(); const second = await api(m, 'PATCH', `/api/v1/reviews/${rid}/pending`, { expected_version: 2, title: `${T1} tab B` }); // a second writer saves first
  ok('E7a', 'a second writer can save first (version 2 to 3)', second.status === 200 && second.json?.version === 3, second.status);
  await a.bringToFront(); await setValue(a, '#edit-title', `${T1} tab A`); await clickText(a, 'button', /^Save$/i);
  await waitText(a, /changed while you were editing/i);
  ok('E7', 'a stale save shows the conflict message, keeps the typed text and offers Reload', (await a.$eval('#edit-title', (e) => e.value)) === `${T1} tab A` && (await hasText(a, /Reload/)));
  await clickText(a, 'button', /Reload/); await sleep(1500);
  ok('E8', 'Reload brings in the latest version (tab B title)', (await a.$eval('#edit-title', (e) => e.value)) === `${T1} tab B`);
  await a.close();

  // ============================== 5. moderator asks for changes ==============================
  await staffLogin();
  ok('M1', 'moderator signs in to the staff app with password and TOTP', true);
  const options = await staffDecide(new RegExp(T1), 'Ask for changes', 'remove-personal-info');
  ok('M2', 'the decision list offers "Ask for changes" next to Publish and Reject', options.some((o) => /Ask for changes/i.test(o)) && options.some((o) => /Publish/i.test(o)), options.join(' | '));
  await m.goto(`${WEB}/account/reviews`, { waitUntil: 'domcontentloaded' });
  await waitCard(m, card, /Changes requested/);
  ok('R1', 'the author now sees "Changes requested" on the list', await m.$eval(card, (e) => /Changes requested/.test(e.innerText)));
  await m.goto(`${WEB}/account/reviews/${rid}`, { waitUntil: 'domcontentloaded' });
  await waitText(m, /remove-personal-info/, 15000).catch(() => {});
  ok('R2', 'the detail page shows the moderator\'s reason', await hasText(m, /remove-personal-info/));
  await shot(m, 'changes-requested');
  await m.goto(`${WEB}/account/reviews/${rid}/edit`, { waitUntil: 'domcontentloaded' }); await m.waitForSelector('#edit-title');
  ok('R3', 'the edit form is still available and repeats the reason', await hasText(m, /remove-personal-info/));
  await setValue(m, '#edit-title', `${T1} fixed`); await clickText(m, 'button', /^Save$/i);
  await waitText(m, /Saved as version/i);
  await m.goto(`${WEB}/account/reviews`, { waitUntil: 'domcontentloaded' }); await waitCard(m, card, /Waiting for moderation/);
  ok('R4', 'after editing, the review is waiting for moderation again', await m.$eval(card, (e) => /Waiting for moderation/.test(e.innerText)));

  // ============================== 6. publish; controls change; public list ==============================
  await staffDecide(new RegExp(T1), 'Publish', 'meets-policy');
  await m.goto(`${WEB}/account/reviews`, { waitUntil: 'domcontentloaded' }); await waitCard(m, card, /Published/);
  ok('P1', 'a published review has no Edit button but can be withdrawn', await m.$eval(card, (e) => !/Edit/.test(e.innerText) && /Withdraw/.test(e.innerText)));
  await m.goto(`${WEB}/account/reviews/${rid}/edit`, { waitUntil: 'domcontentloaded' });
  await waitText(m, /can no longer be edited/i, 10000).catch(() => {});
  ok('P2', 'opening the edit URL of a published review shows "can no longer be edited"', await hasText(m, /can no longer be edited/i));
  await m.goto(`${WEB}/destinations/${D1.id}`, { waitUntil: 'domcontentloaded' }); await waitText(m, new RegExp(`${T1} fixed|${T1}`));
  ok('P3', 'the published review appears on the public destination page', true);
  await waitText(m, /Review filters|Rating/i);
  ok('F1', 'the public review list shows a filter bar', await m.$('form[aria-label="Review filters"]') !== null);
  await m.select('#feed-rating', '1'); await sleep(300);
  ok('F2', 'filtering to 1 star hides a 4-star review and explains why', await hasText(m, /No loaded review matches/i));
  await m.select('#feed-rating', '0'); await sleep(300);
  ok('F3', 'clearing the rating filter brings it back', await hasText(m, new RegExp(T1)));
  await m.select('#feed-author', 'guest'); await sleep(300);
  ok('F4', 'the "Guests" author filter hides a member review', !(await hasText(m, new RegExp(`${T1}`))) || (await hasText(m, /No loaded review matches/i)));
  await m.select('#feed-author', 'all');
  await shot(m, 'public-filters');

  // ============================== 7. pagination on My reviews ==============================
  const { execFileSync } = await import('node:child_process');
  const made = Number(execFileSync('uv', ['run', '--frozen', 'python', path.join(HERE, 'seed_bulk.py'), MEMBER, D2.id, STAMP, '23', String(40 + RUN * 25)], { cwd: 'C:/CSE 3-1/CSE 3102 (LAB)/Abhijatri/backend', env: { ...process.env, PYTHONPATH: '.' }, encoding: 'utf8' }).trim().split(/\s+/).pop());
  await m.goto(`${WEB}/account/reviews`, { waitUntil: 'domcontentloaded' }); await waitText(m, /Show more reviews/i);
  const first = await m.$$eval('li[data-review-id]', (l) => l.length);
  ok('G1', `the first page shows 20 reviews and a "Show more" button (${made} bulk reviews added)`, first === 20 && (await hasText(m, /Show more reviews/i)), first);
  await clickText(m, 'button', /Show more reviews/i); await sleep(1500);
  const ids = await m.$$eval('li[data-review-id]', (l) => l.map((x) => x.dataset.reviewId));
  ok('G2', 'loading more appends the rest with no duplicates', ids.length > 20 && new Set(ids).size === ids.length, ids.length);
  for (let k = 0; k < 6 && (await hasText(m, /Show more reviews/i)); k += 1) { await clickText(m, 'button', /Show more reviews/i); await sleep(1500); }
  ok('G3', 'at the end the list says "That is all your reviews."', await hasText(m, /That is all your reviews/i));
  await m.select('#my-status', 'PENDING'); await sleep(1500);
  const pending = await m.$$eval('li[data-review-id] [data-status]', (l) => l.map((x) => x.dataset.status));
  ok('G4', 'the status filter resets to page 1 and shows only that status', pending.length > 0 && pending.every((s) => s === 'PENDING') && /status=PENDING/.test(m.url()), `${pending.length} ${m.url()}`);
  await m.select('#my-status', 'DELETED'); await sleep(1200);
  ok('G5', 'a filter with no match shows the empty message', await hasText(m, /No reviews match these filters/i));
  await m.select('#my-status', ''); await m.select('#my-destination', D1.id); await sleep(1500);
  const names = await m.$$eval('li[data-review-id] p.font-title', (l) => l.map((x) => x.innerText));
  ok('G6', 'the destination filter narrows the list to that destination only', names.length > 0 && names.every((n) => n.includes(D1.name_en)) && /destination=/.test(m.url()), `${names.length} ${names[0]}`);
  await m.select('#my-destination', '');

  // ============================== 8. withdraw with confirmation ==============================
  await m.goto(`${WEB}/account/reviews`, { waitUntil: 'domcontentloaded' }); await waitText(m, /Bulk/);
  const bulk = await m.$eval('li[data-review-id]', (e) => e.dataset.reviewId);
  const bsel = `li[data-review-id="${bulk}"]`;
  await (await m.$(`${bsel} button`)).click().catch(() => {});
  await m.evaluate((sel) => [...document.querySelectorAll(`${sel} button`)].find((b) => /Withdraw/.test(b.innerText))?.click(), bsel);
  ok('W1', 'Withdraw asks for confirmation first', await hasText(m, /Are you sure/i));
  await m.evaluate((sel) => [...document.querySelectorAll(`${sel} button`)].find((b) => /^Cancel$/.test(b.innerText.trim()))?.click(), bsel);
  ok('W2', 'Cancel leaves the review untouched', !(await hasText(m, /Are you sure/i)));
  await m.evaluate((sel) => [...document.querySelectorAll(`${sel} button`)].find((b) => /Withdraw/.test(b.innerText))?.click(), bsel);
  await m.evaluate((sel) => [...document.querySelectorAll(`${sel} button`)].find((b) => /Yes, withdraw/.test(b.innerText))?.click(), bsel);
  await waitText(m, /Review withdrawn/i);
  ok('W3', 'confirming withdraws it, shows the notice and the card turns "Withdrawn"', await m.$eval(bsel, (e) => /Withdrawn/.test(e.innerText) && !/Edit/.test(e.innerText)));
  const again = await api(m, 'POST', `/api/v1/reviews/${bulk}/withdraw`, { expected_version: 1 });
  ok('W4', 'withdrawing again is accepted (idempotent retry)', again.status === 200 && again.json?.status === 'WITHDRAWN', again.status);

  // ============================== 9. ownership, offline, language, layout ==============================
  const other = await mctx.newPage();
  await other.close();
  const guestOnly = await browser.createBrowserContext(); const g0 = await newPage(guestOnly);
  await g0.goto(`${WEB}/account/reviews`, { waitUntil: 'domcontentloaded' });
  await waitText(g0, /Sign in to see your reviews/i, 10000).catch(() => {});
  ok('O1', 'signed out, My reviews shows a sign-in prompt, not a blank page', await hasText(g0, /Sign in to see your reviews/i));
  const foreign = await g0.evaluate(async (API, id) => (await fetch(`${API}/api/v1/reviews/${id}`, { credentials: 'include' })).status, API, rid);
  ok('O2', 'the review detail API refuses a signed-out caller (401)', foreign === 401, foreign);
  const missing = await api(m, 'GET', `/api/v1/reviews/${crypto.randomUUID()}`);
  ok('O3', 'an unknown review id answers 404', missing.status === 404, missing.status);
  await m.goto(`${WEB}/account/reviews/${crypto.randomUUID()}`, { waitUntil: 'domcontentloaded' });
  await waitText(m, /not found/i, 10000).catch(() => {});
  ok('O4', 'the page for an unknown review says "not found"', await hasText(m, /not found/i));

  await m.goto(`${WEB}/account/reviews`, { waitUntil: 'domcontentloaded' }); await waitText(m, /Bulk/);
  await m.setOfflineMode(true);
  await m.select('#my-status', 'PENDING'); await sleep(1500);
  ok('N1', 'offline, a filter change shows an error with Retry (and no stale list)', (await hasText(m, /Retry/)) && (await hasText(m, /Could not reach the server|offline/i)));
  await m.setOfflineMode(false); await clickText(m, 'button', /Retry/i); await sleep(1800);
  ok('N2', 'back online, Retry reloads the list', (await m.$$eval('li[data-review-id]', (l) => l.length)) > 0);
  await m.select('#my-status', '');

  await m.setViewport({ width: 360, height: 740 }); await m.goto(`${WEB}/account/reviews`, { waitUntil: 'domcontentloaded' }); await waitText(m, /Bulk/);
  const over = await m.evaluate(() => { const w = window.innerWidth; return { sw: document.documentElement.scrollWidth, wide: [...document.querySelectorAll('body *')].filter((e) => e.getBoundingClientRect().right > w + 1 && getComputedStyle(e).position !== 'fixed').slice(0, 4).map((e) => `${e.tagName}.${String(e.className).slice(0, 40)} right=${Math.round(e.getBoundingClientRect().right)}`) }; });
  ok('X1', 'at 360 px wide there is no horizontal scroll', over.sw <= 361, JSON.stringify(over));
  const small = await m.evaluate(() => [...document.querySelectorAll('li[data-review-id] a, li[data-review-id] button')].filter((e) => e.getBoundingClientRect().height < 40).length);
  ok('X2', 'every card control is at least 40 px tall (tap targets)', small === 0, small);
  await shot(m, 'my-reviews-mobile');
  await m.setViewport({ width: 1280, height: 900 });
  await m.goto(`${WEB}/account/reviews`, { waitUntil: 'domcontentloaded' }); await waitText(m, /My reviews/i); await clickText(m, 'button', /^বাংলা$/); await sleep(800);
  ok('X3', 'in Bangla the page heading is in Bangla', await hasText(m, /আমার রিভিউ/));
  await clickText(m, 'button', /^English$/).catch(() => {});
  await m.goto(`${WEB}/account/reviews/${rid}/edit`, { waitUntil: 'domcontentloaded' }); await sleep(1500);
  await m.goto(`${WEB}/account/reviews`, { waitUntil: 'domcontentloaded' });
  const unlabeled = await m.evaluate(() => [...document.querySelectorAll('input,select,textarea')].filter((e) => !e.labels?.length && !e.getAttribute('aria-label') && !e.getAttribute('aria-labelledby')).length);
  ok('X4', 'every form control on My reviews has a label', unlabeled === 0, unlabeled);

  execFileSync('uv', ['run', '--frozen', 'python', path.join(HERE, 'cleanup_bulk.py')], { cwd: 'C:/CSE 3-1/CSE 3102 (LAB)/Abhijatri/backend', env: { ...process.env, PYTHONPATH: '.' }, encoding: 'utf8' });
  // ============================== 10. guest: submit, edit with receipt, rejected, appeal ==============================
  const g = await newPage(guestOnly);
  const T2 = `UI test guest ${STAMP}`;
  await g.goto(`${WEB}/reviews?destination=${D1.id}`, { waitUntil: 'domcontentloaded' }); await g.waitForSelector('#review-title');
  await g.select('#review-destination', D1.id); await setValue(g, '#review-name', 'Rahim Guest');
  await g.$eval('#review-month', (el, v) => { const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set; set.call(el, v); el.dispatchEvent(new Event('input', { bubbles: true })); }, monthsAgo(1));
  await g.click('[role=radio][aria-label="3 stars"]'); await setValue(g, '#review-title', T2);
  await setValue(g, '#review-body', 'The guest review used to test editing and appeals by receipt.');
  await g.click('input[type=checkbox]'); await clickText(g, 'button', /Submit review/i);
  await g.waitForSelector('#receipt-heading', { timeout: 20000 });
  const [grid, receipt] = await g.$$eval('dd.select-all', (d) => d.map((x) => x.innerText.trim()));
  ok('GU1', 'a guest review is created and shows the receipt once', /^abr1_/.test(receipt), receipt?.slice(0, 8));
  const stored = await g.evaluate(() => JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage }));
  ok('GU2', 'the receipt is not kept in browser storage or the URL', !stored.includes('abr1_') && !g.url().includes('abr1_'));
  await clickText(g, 'button', /I have saved/i).catch(() => {}); await g.evaluate(() => document.querySelector('input[type=checkbox]')?.click()).catch(() => {});
  await g.goto(`${WEB}/reviews`, { waitUntil: 'domcontentloaded' }); await g.waitForSelector('#status-review-id');
  await setValue(g, '#status-review-id', grid); await setValue(g, '#status-receipt', receipt); await clickText(g, 'button', /Check status/i);
  await waitText(g, /Waiting for moderation/i);
  ok('GU3', 'the receipt status panel shows "Waiting for moderation" with Edit and Withdraw', (await hasText(g, /Edit review/)) && (await hasText(g, /Withdraw review/)));
  await clickText(g, 'button', /Edit review/i); await g.waitForSelector('#edit-title');
  ok('GU4', 'the guest edit form starts empty and says to fill in only what changes', (await g.$eval('#edit-title', (e) => e.value)) === '' && (await hasText(g, /only what you want to change/i)));
  ok('GU5', 'Save is off until the guest changes something', await g.$eval('form[aria-label="Edit review"] button[type=submit]', (b) => b.disabled)); let gBody = null; let gHdr = null;
  g.on('request', (req) => { if (req.method() === 'PATCH') { gBody = req.postData(); gHdr = req.headers(); }  });
  await setValue(g, '#edit-title', `${T2} edited`); await clickText(g, 'button', /^Save$/i); await waitText(g, /Saved\. Your review is waiting/i);
  const gb = JSON.parse(gBody || '{}');
  ok('GU6', 'the guest PATCH carries the receipt in the body, only the title as content, and no cookie', gb.receipt_secret === receipt && gb.title === `${T2} edited` && !('body' in gb) && !(gHdr?.cookie) && !(gHdr?.['x-csrf-token']), JSON.stringify(Object.keys(gb)));

  await staff.bringToFront(); await staffDecide(new RegExp(T2), 'Reject', 'spam');
  await g.bringToFront(); await clickText(g, 'button', /Check status/i); await waitText(g, /Rejected/i);
  ok('GU7', 'after a rejection the receipt shows the reason and the appeal deadline', (await hasText(g, /spam/i)) && (await hasText(g, /Appeal deadline/i)));
  ok('GU8', 'a rejected review no longer offers Edit', !(await hasText(g, /Edit review/)));
  await clickText(g, 'button', /Appeal this decision/i); await g.waitForSelector('#appeal-statement');
  await setValue(g, '#appeal-statement', 'too short');
  ok('GU9', 'Send appeal stays off below 20 characters and the counter says so', (await g.evaluate(() => [...document.querySelectorAll('button')].find((b) => /Send appeal/.test(b.innerText))?.disabled)) && (await hasText(g, /at least 20/i)));
  await setValue(g, '#appeal-statement', 'This is my honest account of the trip; please look at it again.'); let aUrl = null; let aBody = null;
  g.on('request', (req) => { if (req.url().includes('review-receipts/appeals')) { aUrl = req.url(); aBody = req.postData(); }  });
  await clickText(g, 'button', /Send appeal/i); await waitText(g, /Appeal sent/i);
  ok('GU10', 'the appeal is sent with the receipt in the body only, and the page says "Appeal sent"', aUrl && !aUrl.includes('abr1_') && JSON.parse(aBody).receipt_secret === receipt);
  await clickText(g, 'button', /Check status/i); await waitText(g, /Appeal received/i);
  ok('GU11', 'the status now shows "Appeal received" and no second appeal is offered', !(await hasText(g, /Appeal this decision/i)));
  await shot(g, 'guest-appeal');

  // ============================== 11. staff queue shows the new decision only for waiting reviews ==============================
  const pub = await api(m, 'GET', `/api/v1/reviews/${rid}`);
  ok('M4', 'the owner API view lists the version history and hides moderator-only fields', pub.status === 200 && Array.isArray(pub.json.revisions) && pub.json.revisions.length >= 3 && pub.json.guest_display_name === null && pub.json.conflict_declared === null, pub.status);

  await browser.close();
} catch (err) {
  console.log('SCRIPT ERROR:', err.message.slice(0, 300));
  try { for (const p of await browser.pages()) { await p.screenshot({ path: path.join(SHOTS, 'error.png') }).catch(() => {}); const msgs = await p.evaluate(() => [...document.querySelectorAll('[role=alert],[id$=-error]')].map((e) => e.innerText.trim()).filter(Boolean)).catch(() => []); if (msgs.length) console.log('   page messages:', p.url(), JSON.stringify(msgs)); } } catch {}
  await browser.close().catch(() => {});
  results.push({ id: 'ERR', name: 'script error', pass: false, detail: err.message.slice(0, 200) });
}
const failed = results.filter((r) => !r.pass);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
fs.writeFileSync(path.join(HERE, 'results.json'), JSON.stringify(results, null, 2));
process.exit(failed.length ? 1 : 0);
