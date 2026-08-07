#!/usr/bin/env node
/**
 * Accessibility smoke test for the built VitePress docs site.
 *
 * Implements the automatable slice of #283 TODO 4: heading order, landmark
 * structure, link text, color contrast (light and dark), and image alt
 * text via axe-core's rule set, run against a handful of representative
 * pages rather than every route — axe catches structural/contrast
 * violations; it does not replace real keyboard-navigation or
 * screen-reader testing, which needs a human and isn't attempted here (see
 * the QA report for what's covered vs. not).
 *
 * Requires the site to already be built (`npm run docs:build` in docs/)
 * and scripts/node_modules to have playwright + @axe-core/playwright
 * installed (`npm install` in scripts/, `npx playwright install chromium`).
 *
 * Usage:
 *   node scripts/docs-qa/check_accessibility.mjs
 */
import { chromium } from 'playwright';
import AxeBuilder from '@axe-core/playwright';
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..', '..');
const DIST_DIR = path.join(ROOT, 'docs', '.vitepress', 'dist');

// One page per Diátaxis quadrant plus the two data-heavy generated pages
// (changelog, compatibility matrix) — not exhaustive, but covers every
// distinct layout/content shape the theme renders.
const PAGES = [
  '/',
  '/setup/',
  '/install/web-app',
  '/learn/choose-a-surface',
  '/reference/changelog/',
  '/reference/trust/compatibility',
];

// Pre-existing, acknowledged violations that don't block CI — everything
// else does. This is a baseline, not a suppression: each entry is printed
// as "known" rather than silently dropped, and a NEW violation of the same
// ruleId on a page/theme not listed here still fails the build.
//
// color-contrast on Shiki-highlighted comment tokens: VitePress's default
// syntax theme (github-light/github-dark) renders code comments at #6A737D,
// which measures ~4.45:1 on this site's light code-block background
// (4.5:1 required) and ~3.75:1 in dark mode. The color is set via an
// inline --shiki-light/--shiki-dark custom property per <span>, generated
// per-token by Shiki at build time — there's no class to target, and the
// only two real fixes are (a) picking a different Shiki theme pair, which
// needs visual review across every code sample on the site before landing,
// not a one-line change, or (b) matching on the literal hex value in an
// attribute selector, which is fragile (breaks silently if Shiki's output
// or theme choice ever changes). Neither was safe to do blind in the
// session that found this (#283) — tracked as a real, open gap, not
// swept under the rug.
const KNOWN_VIOLATIONS = [
  { route: '/setup/', theme: 'light', ruleId: 'color-contrast' },
  { route: '/setup/', theme: 'dark', ruleId: 'color-contrast' },
  { route: '/install/web-app', theme: 'light', ruleId: 'color-contrast' },
  { route: '/install/web-app', theme: 'dark', ruleId: 'color-contrast' },
];

function isKnown(route, theme, ruleId) {
  return KNOWN_VIOLATIONS.some((k) => k.route === route && k.theme === theme && k.ruleId === ruleId);
}

const MIME = {
  '.html': 'text/html', '.css': 'text/css', '.js': 'application/javascript',
  '.json': 'application/json', '.svg': 'image/svg+xml', '.webp': 'image/webp',
  '.png': 'image/png', '.ico': 'image/x-icon', '.woff2': 'font/woff2',
};

function startStaticServer(root) {
  const server = createServer(async (req, res) => {
    let urlPath = decodeURIComponent(req.url.split('?')[0]);
    if (urlPath.endsWith('/')) urlPath += 'index.html';
    if (!path.extname(urlPath)) urlPath += '.html';
    const filePath = path.join(root, urlPath);
    if (!filePath.startsWith(root)) {
      res.writeHead(403);
      res.end();
      return;
    }
    try {
      const data = await readFile(filePath);
      res.writeHead(200, { 'Content-Type': MIME[path.extname(filePath)] || 'application/octet-stream' });
      res.end(data);
    } catch {
      res.writeHead(404);
      res.end('not found');
    }
  });
  // Port 0: let the OS assign a free ephemeral port. A fixed port risks
  // silently querying an unrelated process already bound to it instead of
  // this server — which is exactly what happened during development here
  // (a different local app was listening on the first port tried, and its
  // pages were scanned instead of this one, with no error raised).
  return new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => resolve(server));
  });
}

async function run() {
  const server = await startStaticServer(DIST_DIR);
  const { port } = server.address();
  const baseUrl = `http://127.0.0.1:${port}`;
  const browser = await chromium.launch();
  const violationsByPage = [];

  try {
    for (const theme of ['light', 'dark']) {
      const context = await browser.newContext({ colorScheme: theme });
      const page = await context.newPage();
      for (const route of PAGES) {
        const response = await page.goto(`${baseUrl}${route}`, { waitUntil: 'networkidle' });
        if (!response || !response.ok()) {
          throw new Error(`fetching ${route} returned ${response ? response.status() : 'no response'} — the dist build may be missing this page`);
        }
        const results = await new AxeBuilder({ page })
          .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
          .analyze();
        const newViolations = results.violations.filter((v) => !isKnown(route, theme, v.id));
        const knownViolations = results.violations.filter((v) => isKnown(route, theme, v.id));
        if (newViolations.length > 0 || knownViolations.length > 0) {
          violationsByPage.push({ route, theme, newViolations, knownViolations });
        }
      }
      await context.close();
    }
  } finally {
    await browser.close();
    server.close();
  }

  const totalNew = violationsByPage.reduce((sum, p) => sum + p.newViolations.length, 0);
  const totalKnown = violationsByPage.reduce((sum, p) => sum + p.knownViolations.length, 0);

  if (violationsByPage.length > 0) {
    for (const { route, theme, newViolations, knownViolations } of violationsByPage) {
      if (newViolations.length > 0) {
        console.error(`${route} (${theme} mode) — NEW violations:`);
        for (const v of newViolations) {
          console.error(`  - [${v.impact}] ${v.id}: ${v.help} (${v.nodes.length} node(s)) — ${v.helpUrl}`);
          for (const n of v.nodes) {
            console.error(`      ${JSON.stringify(n.target)}: ${n.html.slice(0, 200)}`);
            console.error(`      ${n.failureSummary.replace(/\n/g, ' ')}`);
          }
        }
      }
      if (knownViolations.length > 0) {
        console.error(`${route} (${theme} mode) — known, non-blocking (see KNOWN_VIOLATIONS in this script):`);
        for (const v of knownViolations) {
          console.error(`  - [${v.impact}] ${v.id}: ${v.help} (${v.nodes.length} node(s))`);
        }
      }
    }
  }

  if (totalNew > 0) {
    console.error(`\n${totalNew} new accessibility violation(s) found (plus ${totalKnown} known/non-blocking).`);
    process.exit(1);
  }

  console.log(
    `Accessibility check passed: ${PAGES.length} page(s) x 2 themes (light/dark), wcag2a/wcag2aa/wcag21aa rule sets, ` +
    `0 new violations${totalKnown > 0 ? ` (${totalKnown} known/acknowledged, see KNOWN_VIOLATIONS)` : ''}.`
  );
}

run().catch((err) => {
  console.error('Accessibility check crashed:', err);
  process.exit(2);
});
