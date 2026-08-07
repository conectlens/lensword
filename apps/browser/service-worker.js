const MENU_ID = 'lensword-save-selection'
const DEFAULTS = { apiUrl: 'http://localhost:18420', token: '', groupId: '' }

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
      message: 'Open the extension popup to set an API token and group.',
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
    await chrome.notifications.create(`lensword-error-${Date.now()}`, {
      type: 'basic',
      iconUrl: 'icons/icon48.png',
      title: 'LensWord capture failed',
      message: error instanceof Error ? error.message : 'Could not save selection.',
    })
  }
})

async function saveWord(settings, term) {
  const response = await fetch(`${settings.apiUrl.replace(/\/$/, '')}/api/v1/groups/${encodeURIComponent(settings.groupId)}/words`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${settings.token}` },
    body: JSON.stringify({ term, target_language: 'Spanish', translations: [] }),
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail || `Server returned ${response.status}.`)
  }
  return response.json()
}
