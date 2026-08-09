import { API_URL } from './config.js'

const MENU_ID = 'lensword-save-selection'
const DEFAULTS = { token: '', groupId: '' }

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: MENU_ID,
    title: 'Save “%s” to LensWord',
    contexts: ['selection'],
  })
})

chrome.contextMenus.onClicked.addListener(async (info) => {
  if (info.menuItemId !== MENU_ID || !info.selectionText?.trim()) return
  const settings = { ...DEFAULTS, ...(await chrome.storage.local.get(DEFAULTS)) }
  if (!settings.token || !settings.groupId) {
    await chrome.notifications.create('lensword-settings-required', {
      type: 'basic',
      iconUrl: 'icons/icon48.png',
      title: 'LensWord needs setup',
      message: 'Open the extension popup, sign in, and choose a group.',
    })
    return
  }
  try {
    await saveWord(settings, info.selectionText.trim())
    await chrome.notifications.create(`lensword-saved-${Date.now()}`, {
      type: 'basic',
      iconUrl: 'icons/icon48.png',
      title: 'Saved to LensWord',
      message: info.selectionText.trim().slice(0, 80),
    })
  } catch (error) {
    const expired = error instanceof Error && error.status === 401
    await chrome.notifications.create(`lensword-error-${Date.now()}`, {
      type: 'basic',
      iconUrl: 'icons/icon48.png',
      title: expired ? 'LensWord session expired' : 'LensWord capture failed',
      message: expired
        ? 'Open the extension popup and sign in again.'
        : error instanceof Error
          ? error.message
          : 'Could not save selection.',
    })
    if (expired) await chrome.storage.local.remove(['token', 'groupId', 'email'])
  }
})

async function saveWord(settings, term) {
  const response = await fetch(`${API_URL.replace(/\/$/, '')}/api/v1/groups/${encodeURIComponent(settings.groupId)}/words`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${settings.token}` },
    body: JSON.stringify({ term, target_language: 'Spanish', translations: [] }),
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    const error = new Error(body.detail || `Server returned ${response.status}.`)
    error.status = response.status
    throw error
  }
  return response.json()
}
