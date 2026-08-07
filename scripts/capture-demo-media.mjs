#!/usr/bin/env node
// Reproducible LensWord demo-media capture.
//
// Seeds a dedicated, synthetic demo account (no personal data — see the
// constants below) against a running backend, then drives a fixed sequence
// of real UI states with Playwright and screenshots each one. Frames are
// assembled into an animated WebP (see assemble-demo-animation.py) rather
// than hand-staged mockups, so every pixel in the resulting animation is
// something the application actually rendered.
//
// Usage:
//   docker compose up --build            # from the repo root, in another terminal
//   cd apps/frontend && npm ci           # if not already installed
//   npm --prefix apps/frontend install --no-save playwright   # if not already installed
//   npx --prefix apps/frontend playwright install chromium    # if not already installed
//   node scripts/capture-demo-media.mjs
//
// Writes numbered PNG frames to docs/media/demo-frames/review-session/ and
// prints the exact revision/fixture recorded for this run. Re-run
// assemble-demo-animation.py afterward to produce the animated WebP.

import { chromium } from 'playwright'
import { mkdirSync, writeFileSync } from 'node:fs'
import { execSync } from 'node:child_process'

const API_URL = process.env.LENSWORD_API_URL || 'http://localhost:18420'
const FRONTEND_URL = process.env.LENSWORD_FRONTEND_URL || 'http://localhost:18421'
const OUT_DIR = 'docs/media/demo-frames/review-session'

// Synthetic demo identity — not a real person, not reused anywhere else.
// The password is intentionally throwaway; this account exists only inside
// a local, disposable docker-compose Postgres volume.
const DEMO = {
  username: 'demo_reviewer',
  email: 'demo.reviewer@example.com',
  password: 'DemoReviewer123!',
  groupName: 'Spanish Verbs',
  targetLanguage: 'Spanish',
  words: [
    { term: 'hablar', translations: ['to speak'], example_sentence: 'Quiero hablar contigo.' },
    { term: 'el recuerdo', translations: ['the memory'], example_sentence: 'Guardo ese recuerdo con cariño.' },
    { term: 'el viaje', translations: ['the trip / journey'], example_sentence: 'Planeamos un viaje a Madrid.' },
  ],
}

async function api(path, opts = {}) {
  const res = await fetch(`${API_URL}${path}`, {
    ...opts,
    headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
  })
  const body = await res.json().catch(() => ({}))
  return { status: res.status, body }
}

async function seed() {
  console.log('Seeding demo account and fixture data...')
  let token
  const registered = await api('/api/v1/auth/register', {
    method: 'POST',
    body: JSON.stringify({ username: DEMO.username, email: DEMO.email, password: DEMO.password }),
  })
  if (registered.status === 201 || registered.status === 200) {
    token = registered.body?.token?.access_token
    console.log('  registered new demo account')
  } else {
    const login = await api('/api/v1/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email: DEMO.email, password: DEMO.password }),
    })
    if (login.status !== 200) throw new Error(`Could not register or log in demo account: ${JSON.stringify(login.body)}`)
    token = login.body.token.access_token
    console.log('  reused existing demo account')
  }

  const auth = { Authorization: `Bearer ${token}` }

  const groups = await api('/api/v1/groups', { headers: auth })
  let group = groups.body.find?.((g) => g.name === DEMO.groupName)
  if (!group) {
    const created = await api('/api/v1/groups', {
      method: 'POST',
      headers: auth,
      body: JSON.stringify({ name: DEMO.groupName, target_language: DEMO.targetLanguage }),
    })
    group = created.body
    console.log(`  created group "${DEMO.groupName}" (id ${group.id})`)
  } else {
    console.log(`  reused group "${DEMO.groupName}" (id ${group.id})`)
  }

  const existingWords = await api(`/api/v1/groups/${group.id}/words`, { headers: auth })
  const existingTerms = new Set((existingWords.body || []).map((w) => w.term))
  for (const word of DEMO.words) {
    if (existingTerms.has(word.term)) continue
    await api(`/api/v1/groups/${group.id}/words`, {
      method: 'POST',
      headers: auth,
      body: JSON.stringify({ term: word.term, target_language: DEMO.targetLanguage, translations: word.translations, example_sentence: word.example_sentence }),
    })
    console.log(`  added word "${word.term}"`)
  }

  return { token, groupId: group.id }
}

async function capture({ groupId }) {
  mkdirSync(OUT_DIR, { recursive: true })
  const browser = await chromium.launch()
  const context = await browser.newContext({ viewport: { width: 1200, height: 675 }, colorScheme: 'dark', locale: 'en-US' })
  const page = await context.newPage()

  await page.goto(`${FRONTEND_URL}/login`, { waitUntil: 'networkidle' })
  await page.locator('input[type=email]').fill(DEMO.email)
  await page.locator('input[type=password]').fill(DEMO.password)
  await page.getByRole('button', { name: 'Log in' }).click()
  await page.waitForURL('**/dashboard', { timeout: 10000 })

  await page.goto(`${FRONTEND_URL}/review?mode=standard&group=${groupId}`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(600)
  await page.screenshot({ path: `${OUT_DIR}/01-question.png` })
  console.log('  captured 01-question.png')

  // Which word appears first depends on spaced-repetition state, which
  // shifts as this script is re-run (answering a word moves its next-due
  // date). Read the word actually on screen and look up its real
  // translation rather than assuming a fixed word/answer pairing, so the
  // capture stays correct — and demonstrates a real "Correct!" — on every
  // run, not just a freshly-seeded one.
  const shownTerm = (await page.locator('h1, h2').filter({ hasText: /./ }).first().innerText()).trim().toLowerCase()
  const matched = DEMO.words.find((w) => w.term.toLowerCase() === shownTerm)
  const correctAnswer = matched ? matched.translations[0] : 'to speak'
  if (!matched) console.warn(`  warning: shown word "${shownTerm}" not found in fixture; falling back to "${correctAnswer}"`)

  const answerInput = page.locator('input[placeholder="Your answer..."]')
  await answerInput.click()
  await page.waitForTimeout(300)
  await answerInput.pressSequentially(correctAnswer, { delay: 45 })
  await page.waitForTimeout(400)
  await page.screenshot({ path: `${OUT_DIR}/02-typed.png` })
  console.log('  captured 02-typed.png')

  await page.getByRole('button', { name: 'Check' }).click()
  // The app shows "Correct!"/"Not quite" feedback for exactly 500ms
  // (ReviewSessionPage.tsx's submitOutcome) before auto-advancing — capture
  // inside that window, not after it closes.
  await page.waitForTimeout(250)
  await page.screenshot({ path: `${OUT_DIR}/03-result.png` })
  console.log('  captured 03-result.png')

  await page.waitForTimeout(1000)
  await page.screenshot({ path: `${OUT_DIR}/04-next.png` })
  console.log('  captured 04-next.png')

  await browser.close()
}

function recordProvenance() {
  let rev = 'unknown'
  try {
    rev = execSync('git rev-parse HEAD', { encoding: 'utf-8' }).trim()
  } catch {
    // not fatal — provenance is best-effort
  }
  const provenance = {
    generatedFrom: OUT_DIR,
    scenario: 'web-review-session',
    revision: rev,
    fixture: DEMO,
    generatedAt: 'set by generation script at run time — see git blame on this JSON file for the actual date',
  }
  writeFileSync(`${OUT_DIR}/provenance.json`, JSON.stringify(provenance, null, 2))
  console.log(`  wrote provenance.json (revision ${rev.slice(0, 12)})`)
}

const { token, groupId } = await seed()
await capture({ groupId })
recordProvenance()
console.log('\nDone. Run scripts/assemble-demo-animation.py next to build the animated WebP.')
