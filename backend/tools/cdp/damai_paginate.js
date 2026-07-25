/**
 * Drive isolated Chrome (CDP :9333) to paginate damai search results.
 * Stops when fruit-slider / baxia captcha is detected.
 *
 * Usage:
 *   node damai_paginate.js [--max-pages N] [--out dir]
 */
const http = require('http');
const fs = require('fs');
const path = require('path');
const WebSocket = require('ws');

const CDP_HOST = process.env.CDP_HOST || '127.0.0.1';
const CDP_PORT = process.env.CDP_PORT || '9333';
const START_URL =
  process.env.DAMAI_URL ||
  'https://search.damai.cn/search.htm?spm=a2oeg.home.top.dcategory.25fe23e1tIArSA&order=1';

function parseArgs() {
  const args = process.argv.slice(2);
  let maxPages = 30;
  let outDir = path.join(__dirname, '..', 'damai_search_pages');
  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--max-pages') maxPages = Number(args[++i]);
    else if (args[i] === '--out') outDir = args[++i];
  }
  return { maxPages, outDir };
}

function httpGet(url) {
  return new Promise((resolve, reject) => {
    http
      .get(url, (r) => {
        let d = '';
        r.on('data', (c) => (d += c));
        r.on('end', () => {
          try {
            resolve(JSON.parse(d));
          } catch (e) {
            reject(new Error(`Bad JSON from ${url}: ${d.slice(0, 200)}`));
          }
        });
      })
      .on('error', reject);
  });
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function getOrCreatePage() {
  const base = `http://${CDP_HOST}:${CDP_PORT}`;
  let list = await httpGet(`${base}/json/list`);
  let page = list.find(
    (t) =>
      t.type === 'page' &&
      (t.url.startsWith('http') || t.url === 'about:blank' || t.url.startsWith('chrome://new'))
  );
  if (!page) {
    page = list.find((t) => t.type === 'page');
  }
  if (!page) {
    // PUT /json/new is more reliable on some Chrome builds
    page = await new Promise((resolve, reject) => {
      const req = http.request(
        {
          host: CDP_HOST,
          port: CDP_PORT,
          path: '/json/new?about:blank',
          method: 'PUT',
        },
        (r) => {
          let d = '';
          r.on('data', (c) => (d += c));
          r.on('end', () => {
            try {
              resolve(JSON.parse(d));
            } catch (e) {
              reject(e);
            }
          });
        }
      );
      req.on('error', reject);
      req.end();
    });
  }
  return page;
}

class Cdp {
  constructor(wsUrl) {
    this.wsUrl = wsUrl;
    this.id = 0;
    this.pending = new Map();
    this.ws = null;
  }
  async connect() {
    this.ws = new WebSocket(this.wsUrl);
    this.ws.on('message', (raw) => {
      const msg = JSON.parse(raw.toString());
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        if (msg.error) reject(new Error(JSON.stringify(msg.error)));
        else resolve(msg.result);
      }
    });
    await new Promise((resolve, reject) => {
      this.ws.once('open', resolve);
      this.ws.once('error', reject);
    });
  }
  send(method, params = {}) {
    return new Promise((resolve, reject) => {
      const id = ++this.id;
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
  evaluate(expression) {
    return this.send('Runtime.evaluate', {
      expression,
      returnByValue: true,
      awaitPromise: true,
    }).then((r) => {
      if (r.exceptionDetails) {
        throw new Error(JSON.stringify(r.exceptionDetails));
      }
      return r.result?.value;
    });
  }
  close() {
    try {
      this.ws.close();
    } catch (_) {}
  }
}

const EXTRACT_JS = `(() => {
  const captchaSelectors = [
    '#baxia-punish',
    '.baxia-dialog',
    '.baxia-dialog-content',
    'iframe[src*="punish"]',
    'iframe[src*="captcha"]',
    'iframe[src*="nocaptcha"]',
    '[class*="nc_wrapper"]',
    '#nc_1_n1z',
    '.nc_scale',
    '[class*="captcha"]',
    'img[src*="ques"]',
  ];
  const captchaHit = captchaSelectors.map(s => ({
    s,
    n: document.querySelectorAll(s).length,
  })).filter(x => x.n > 0);
  const bodyText = (document.body && document.body.innerText) || '';
  const fruitHint = /水果|拖动|滑块|请完成验证|验证码|点击完成验证/.test(bodyText);
  const title = document.title || '';

  // Damai search item cards (several historical class names)
  const cardSelectors = [
    '.items .item',
    '.item__box',
    '.search__itemlist .items .item',
    '#content .items .item',
    '.item__box .items__item',
  ];
  let cards = [];
  for (const sel of cardSelectors) {
    const nodes = Array.from(document.querySelectorAll(sel));
    if (nodes.length) { cards = nodes; break; }
  }
  // Fallback: links to detail
  if (!cards.length) {
    cards = Array.from(document.querySelectorAll('a[href*="detail.damai.cn"], a[href*="/event"]'))
      .map(a => a.closest('div') || a)
      .filter((el, i, arr) => arr.indexOf(el) === i)
      .slice(0, 60);
  }

  const items = cards.map((el, idx) => {
    const a = el.querySelector('a[href]') || (el.tagName === 'A' ? el : null);
    const href = a ? a.href : '';
    const titleEl = el.querySelector('.items__txt__title, .item__box__title, .title, h3, .items__txt') || a;
    const name = (titleEl && titleEl.textContent || '').replace(/\\s+/g, ' ').trim();
    const venue = (el.querySelector('.items__txt__venue, .venue, .items__txt__time + *') || {}).textContent || '';
    const time = (el.querySelector('.items__txt__time, .time, .showtime') || {}).textContent || '';
    const price = (el.querySelector('.items__txt__price, .price, .items__txt__price__num') || {}).textContent || '';
    const city = (el.querySelector('.items__txt__city, .city') || {}).textContent || '';
    const status = (el.querySelector('.items__txt__tag, .tag, .status') || {}).textContent || '';
    return {
      idx,
      name: name.slice(0, 200),
      href,
      venue: venue.replace(/\\s+/g, ' ').trim().slice(0, 120),
      time: time.replace(/\\s+/g, ' ').trim().slice(0, 120),
      price: price.replace(/\\s+/g, ' ').trim().slice(0, 80),
      city: city.replace(/\\s+/g, ' ').trim().slice(0, 40),
      status: status.replace(/\\s+/g, ' ').trim().slice(0, 40),
    };
  }).filter(x => x.name || x.href);

  // pagination state
  const activePage =
    document.querySelector('.pagination .number.active, .pagination li.active, .pg-item.active, span.current') ||
    document.querySelector('[class*="pagination"] .active');
  const pageText = activePage ? activePage.textContent.trim() : '';
  const nextBtn =
    document.querySelector('.pagination .btn-next:not(.disabled), .pagination .next:not(.disabled), a.next:not(.disabled), li.next:not(.disabled) a') ||
    Array.from(document.querySelectorAll('a, button, span, li')).find(el => {
      const t = (el.textContent || '').trim();
      return t === '下一页' || t === '下页' || t === '>';
    });

  return {
    title,
    href: location.href,
    captcha: captchaHit.length > 0 || fruitHint,
    captchaHit,
    fruitHint,
    itemCount: items.length,
    items,
    pageText,
    hasNext: !!nextBtn,
    bodySnippet: bodyText.slice(0, 400),
  };
})()`;

const CLICK_NEXT_JS = `(() => {
  const candidates = [
    document.querySelector('.pagination .btn-next:not(.disabled)'),
    document.querySelector('.pagination .next:not(.disabled)'),
    document.querySelector('a.next:not(.disabled)'),
    document.querySelector('li.next:not(.disabled) a'),
    document.querySelector('.number.active + .number'),
    document.querySelector('.pg-item.active + .pg-item'),
  ].filter(Boolean);
  let el = candidates[0];
  if (!el) {
    el = Array.from(document.querySelectorAll('a, button, span, li')).find(n => {
      const t = (n.textContent || '').trim();
      return t === '下一页' || t === '下页';
    });
  }
  if (!el) return { ok: false, reason: 'no next button' };
  el.click();
  return { ok: true, text: (el.textContent || '').trim().slice(0, 40) };
})()`;

async function main() {
  const { maxPages, outDir } = parseArgs();
  fs.mkdirSync(outDir, { recursive: true });
  const all = [];
  const summary = { pages: [], stopped: null, captcha: false };

  const page = await getOrCreatePage();
  console.log('[cdp] page', page.id, page.url);
  const cdp = new Cdp(page.webSocketDebuggerUrl);
  await cdp.connect();
  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');
  await cdp.send('Network.enable');

  console.log('[nav]', START_URL);
  await cdp.send('Page.navigate', { url: START_URL });
  await sleep(6000);

  for (let p = 1; p <= maxPages; p++) {
    // wait a bit for XHR list render
    await sleep(p === 1 ? 2000 : 3500);
    let data;
    for (let attempt = 0; attempt < 5; attempt++) {
      data = await cdp.evaluate(EXTRACT_JS);
      if (data.captcha || data.itemCount > 0) break;
      await sleep(1500);
    }

    const pageFile = path.join(outDir, `page_${String(p).padStart(3, '0')}.json`);
    fs.writeFileSync(pageFile, JSON.stringify(data, null, 2));
    console.log(
      `[page ${p}] items=${data.itemCount} captcha=${data.captcha} pageText=${data.pageText} hasNext=${data.hasNext}`
    );
    if (data.items?.length) {
      for (const it of data.items) {
        all.push({ ...it, crawlPage: p, crawledAt: new Date().toISOString() });
      }
    }
    summary.pages.push({
      page: p,
      itemCount: data.itemCount,
      captcha: data.captcha,
      href: data.href,
      file: pageFile,
    });

    if (data.captcha) {
      summary.stopped = 'captcha';
      summary.captcha = true;
      // screenshot via Page.captureScreenshot
      try {
        const shot = await cdp.send('Page.captureScreenshot', { format: 'png' });
        const shotPath = path.join(outDir, `captcha_page_${p}.png`);
        fs.writeFileSync(shotPath, Buffer.from(shot.data, 'base64'));
        summary.captchaScreenshot = shotPath;
        console.log('[captcha] screenshot', shotPath);
      } catch (e) {
        console.warn('[captcha] screenshot failed', e.message);
      }
      console.log('\n=== CAPTCHA DETECTED — please solve manually in the isolated Chrome window ===');
      console.log('Profile/CDP: http://127.0.0.1:9333  (data/browser_profile_iso)');
      console.log('After solving, re-run with --start-page or tell the agent to continue.\n');
      break;
    }

    if (!data.hasNext || data.itemCount === 0) {
      summary.stopped = data.itemCount === 0 ? 'empty' : 'no_next';
      break;
    }

    const clicked = await cdp.evaluate(CLICK_NEXT_JS);
    console.log('[next]', clicked);
    if (!clicked?.ok) {
      summary.stopped = 'click_next_failed';
      break;
    }
    await sleep(2500);
  }

  const allPath = path.join(outDir, 'all_items.json');
  fs.writeFileSync(allPath, JSON.stringify(all, null, 2));
  const sumPath = path.join(outDir, 'summary.json');
  fs.writeFileSync(sumPath, JSON.stringify({ ...summary, totalItems: all.length }, null, 2));
  console.log('[done]', { totalItems: all.length, stopped: summary.stopped, allPath, sumPath });
  cdp.close();
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
