import { API_URL } from './config.js'

const els = {
  signedOut: document.querySelector('#signed-out'),
  signedIn: document.querySelector('#signed-in'),
  email: document.querySelector('#email'),
  password: document.querySelector('#password'),
  signIn: document.querySelector('#sign-in'),
  account: document.querySelector('#account'),
  group: document.querySelector('#group'),
  signOut: document.querySelector('#sign-out'),
  status: document.querySelector('#status'),
}

function setStatus(message, isError = false) {
  els.status.textContent = message
  els.status.classList.toggle('error', isError)
}

function showSignedOut() {
  els.signedOut.hidden = false
  els.signedIn.hidden = true
}

function showSignedIn() {
  els.signedOut.hidden = true
  els.signedIn.hidden = false
}

async function requestOriginPermission() {
  const origin = new URL(API_URL).origin + '/*'
  const granted = await chrome.permissions.request({ origins: [origin] })
  if (!granted) throw new Error('The API origin permission was not granted.')
}

async function apiFetch(path, options = {}) {
  const response = await fetch(`${API_URL.replace(/\/$/, '')}${path}`, options)
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    const error = new Error(body.detail || `Server returned ${response.status}.`)
    error.status = response.status
    throw error
  }
  return response.json()
}

async function loadGroups(token, selectedGroupId) {
  els.group.replaceChildren()
  try {
    const groups = await apiFetch('/api/v1/groups', {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (groups.length === 0) {
      setStatus('You have no groups yet — create one in the LensWord web app first.', true)
      els.group.disabled = true
      return
    }
    els.group.disabled = false
    for (const group of groups) {
      const option = document.createElement('option')
      option.value = String(group.id)
      option.textContent = `${group.name} (${group.target_language})`
      els.group.appendChild(option)
    }
    const hasSelected = selectedGroupId && groups.some((g) => String(g.id) === String(selectedGroupId))
    els.group.value = hasSelected ? String(selectedGroupId) : String(groups[0].id)
    if (!hasSelected) await chrome.storage.local.set({ groupId: els.group.value })
  } catch (error) {
    if (error.status === 401) {
      await signOut('Your session expired. Sign in again.')
      return
    }
    setStatus(error instanceof Error ? error.message : 'Could not load groups.', true)
  }
}

async function signOut(message) {
  await chrome.storage.local.remove(['token', 'groupId', 'email'])
  showSignedOut()
  if (message) setStatus(message, true)
}

els.signIn.addEventListener('click', async () => {
  const email = els.email.value.trim()
  const password = els.password.value
  if (!email || !password) {
    setStatus('Enter your email and password.', true)
    return
  }
  els.signIn.disabled = true
  setStatus('Signing in…')
  try {
    await requestOriginPermission()
    const { user, token } = await apiFetch('/api/v1/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    })
    await chrome.storage.local.set({ token: token.access_token, email: user.email })
    els.password.value = ''
    els.account.textContent = `Signed in as ${user.email}`
    showSignedIn()
    setStatus('')
    await loadGroups(token.access_token, null)
  } catch (error) {
    setStatus(error instanceof Error ? error.message : 'Could not sign in.', true)
  } finally {
    els.signIn.disabled = false
  }
})

els.group.addEventListener('change', async () => {
  await chrome.storage.local.set({ groupId: els.group.value })
})

els.signOut.addEventListener('click', () => signOut())

async function load() {
  const stored = await chrome.storage.local.get(['token', 'groupId', 'email'])
  if (!stored.token) {
    showSignedOut()
    return
  }
  els.account.textContent = `Signed in as ${stored.email}`
  showSignedIn()
  await loadGroups(stored.token, stored.groupId)
}

load()
