const DEFAULTS = { apiUrl: 'http://localhost:18420', token: '', groupId: '' }
const fields = { apiUrl: document.querySelector('#api-url'), token: document.querySelector('#token'), groupId: document.querySelector('#group-id') }
const status = document.querySelector('#status')

async function load() {
  const settings = { ...DEFAULTS, ...(await chrome.storage.local.get(DEFAULTS)) }
  for (const [key, field] of Object.entries(fields)) field.value = settings[key]
}

document.querySelector('#save').addEventListener('click', async () => {
  const settings = Object.fromEntries(Object.entries(fields).map(([key, field]) => [key, field.value.trim()]))
  if (!settings.apiUrl || !settings.token || !/^[1-9]\d*$/.test(settings.groupId)) {
    status.textContent = 'Enter an API URL, token, and positive group ID.'
    return
  }
  try {
    const origin = new URL(settings.apiUrl).origin + '/*'
    const granted = await chrome.permissions.request({ origins: [origin] })
    if (!granted) throw new Error('The API origin permission was not granted.')
    await chrome.storage.local.set(settings)
    status.textContent = 'Settings saved.'
  } catch (error) {
    status.textContent = error instanceof Error ? error.message : 'Could not save settings.'
  }
})

load()
