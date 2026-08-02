import type {
  AdminStats, Group, MnemonicNote, ProfileOverview, RecallSettings, Room,
  SessionMode, SessionSummary, SupportedLanguage, User, Word, ReviewOutcome, AISettings, WordEnrichment, DailySession, PracticeExercise, WeeklyLearningReport, PendingDesktopNotifications, NotificationActionId, NotificationActionResult, WeaknessProfile, CefrProgress, Prerequisites, RelatedWord,
} from './types'
import { resolveApiBase } from './runtimeConfig'

// The token lives behind a typed adapter: `localStorage` in the browser, the OS
// credential store in the desktop shell (ADR 0001). Re-exported here so the
// public API surface — and its callers — stay unchanged.
import { getToken, setToken, clearToken, hydrateToken } from './credentialStore'
export { getToken, setToken, clearToken, hydrateToken }

export class ApiRequestError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken()
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> | undefined),
  }
  if (token) headers.Authorization = `Bearer ${token}`

  // Resolved rather than compiled in: the desktop shell supplies its own
  // validated endpoint, and one build has to serve both it and the browser.
  const res = await fetch(`${await resolveApiBase()}${path}`, { ...options, headers })

  if (res.status === 204) return undefined as T

  const isJson = res.headers.get('content-type')?.includes('application/json')
  const body = isJson ? await res.json() : undefined

  if (!res.ok) {
    const message = body?.detail ?? `Request failed with status ${res.status}`
    throw new ApiRequestError(res.status, typeof message === 'string' ? message : JSON.stringify(message))
  }
  return body as T
}

// --- Auth --------------------------------------------------------------

export interface AuthResponse {
  user: User
  token: { access_token: string; token_type: string }
}

export const authApi = {
  register: (username: string, email: string, password: string) =>
    request<AuthResponse>('/api/v1/auth/register', { method: 'POST', body: JSON.stringify({ username, email, password }) }),
  login: (email: string, password: string) =>
    request<AuthResponse>('/api/v1/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }),
  me: () => request<User>('/api/v1/auth/me'),
}

// --- Groups & Words ------------------------------------------------------

export interface WordInput {
  term: string
  target_language: SupportedLanguage
  translations: string[]
  example_sentence?: string | null
  mnemonic?: string | null
  category?: string | null
  definition?: string | null
  part_of_speech?: string | null
  cefr_level?: string | null
  pronunciation?: string | null
  collocations?: string[]
  tags?: string[]
  ai_confidence?: number | null
  ai_provider?: string | null
  ai_model?: string | null
}

export const aiVocabularyApi = {
  enrich: (term: string, source_language: string | null, target_language: string) =>
    request<WordEnrichment>('/api/v1/ai/enrich', { method: 'POST', body: JSON.stringify({ term, source_language, target_language }) }),
  translateInContext: (word: string, sentence: string, source_language: string | null, target_language: string) =>
    request<WordEnrichment>('/api/v1/ai/translate-in-context', { method: 'POST', body: JSON.stringify({ word, sentence, source_language, target_language }) }),
  regenerateField: (field: 'example' | 'mnemonic' | 'definition' | 'translation', term: string, target_language: string) =>
    request<{ field: string; value: string }>('/api/v1/ai/regenerate-field', { method: 'POST', body: JSON.stringify({ field, term, target_language }) }),
}

export interface ExtractedCandidate { term: string; translations: string[]; examples: string[]; cefr_level: string | null }
export type ExtractVocabularyResult =
  | { status: 'ok'; source: 'ai' | 'fallback'; items: ExtractedCandidate[] }
  | { status: 'disabled' }
  | { status: 'unavailable'; detail: string }

export const extractionApi = {
  extract: (group_id: number, text: string, target_language: string, min_level: string | null, source_language: string | null = null) =>
    request<ExtractVocabularyResult>('/api/v1/extract', { method: 'POST', body: JSON.stringify({ group_id, text, source_language, target_language, min_level }) }),
}

export interface ImportPreviewRecord { term: string; translations: string[]; definition: string | null; part_of_speech: string | null; cefr_level: string | null; pronunciation: string | null; source_language: string; status: 'ready' | 'ai_cleaned' | 'duplicate'; duplicate_of: string | null; provider: string | null; model: string | null }
export const importsApi = {
  parseFile: async (file: File) => {
    const data = new FormData(); data.append('file', file)
    const token = getToken(); const response = await fetch(`${await resolveApiBase()}/api/v1/imports/parse`, { method: 'POST', body: data, headers: token ? { Authorization: `Bearer ${token}` } : {} })
    if (!response.ok) throw new ApiRequestError(response.status, (await response.json()).detail ?? 'Could not parse file')
    return response.json() as Promise<{ records: { term: string; translations: string[]; definition?: string | null; part_of_speech?: string | null; cefr_level?: string | null; pronunciation?: string | null }[] }>
  },
  parseUrl: (url: string) =>
    request<{ records: { term: string; translations: string[] }[] }>('/api/v1/imports/parse-url', {
      method: 'POST',
      body: JSON.stringify({ url }),
    }),
  preview: (group_id: number, records: { term: string; translations?: string[]; definition?: string | null; part_of_speech?: string | null; cefr_level?: string | null; pronunciation?: string | null }[], enrich_with_ai: boolean) => request<{ records: ImportPreviewRecord[] }>('/api/v1/imports/preview', { method: 'POST', body: JSON.stringify({ group_id, records, enrich_with_ai }) }),
  commit: (group_id: number, records: ImportPreviewRecord[]) => request<{ added: number }>('/api/v1/imports/commit', { method: 'POST', body: JSON.stringify({ group_id, records }) }),
}

export const groupsApi = {
  list: () => request<Group[]>('/api/v1/groups'),
  create: (name: string, target_language: SupportedLanguage) =>
    request<Group>('/api/v1/groups', { method: 'POST', body: JSON.stringify({ name, target_language }) }),
  rename: (groupId: number, name: string) =>
    request<Group>(`/api/v1/groups/${groupId}`, { method: 'PATCH', body: JSON.stringify({ name }) }),
  remove: (groupId: number) => request<void>(`/api/v1/groups/${groupId}`, { method: 'DELETE' }),
  words: (groupId: number) => request<Word[]>(`/api/v1/groups/${groupId}/words`),
  addWord: (groupId: number, input: WordInput) =>
    request<Word>(`/api/v1/groups/${groupId}/words`, { method: 'POST', body: JSON.stringify(input) }),
}

export const wordsApi = {
  get: (wordId: number) => request<Word>(`/api/v1/words/${wordId}`),
  update: (wordId: number, input: WordInput) =>
    request<Word>(`/api/v1/words/${wordId}`, { method: 'PUT', body: JSON.stringify(input) }),
  remove: (wordId: number) => request<void>(`/api/v1/words/${wordId}`, { method: 'DELETE' }),
  updateAssociations: (
    wordId: number,
    add: { kind: 'synonym' | 'antonym' | 'topic'; value: string }[],
    remove: { kind: 'synonym' | 'antonym' | 'topic'; value: string }[],
  ) =>
    request<Word>(`/api/v1/words/${wordId}/associations`, {
      method: 'PATCH',
      body: JSON.stringify({ add, remove }),
    }),
}

// --- Rooms ---------------------------------------------------------------

export const roomsApi = {
  list: () => request<Room[]>('/api/v1/rooms'),
  create: (group_id: number, name: string, icon: string) =>
    request<Room>('/api/v1/rooms', { method: 'POST', body: JSON.stringify({ group_id, name, icon }) }),
  get: (roomId: number) => request<Room>(`/api/v1/rooms/${roomId}`),
  words: (roomId: number) => request<Word[]>(`/api/v1/rooms/${roomId}/words`),
  place: (roomId: number, word_id: number, x_percent: number, y_percent: number) =>
    request<Room>(`/api/v1/rooms/${roomId}/placements`, {
      method: 'POST',
      body: JSON.stringify({ word_id, x_percent, y_percent }),
    }),
  unplace: (roomId: number, wordId: number) =>
    request<Room>(`/api/v1/rooms/${roomId}/placements/${wordId}`, { method: 'DELETE' }),
  remove: (roomId: number) => request<void>(`/api/v1/rooms/${roomId}`, { method: 'DELETE' }),
}

// --- Review ----------------------------------------------------------------

export interface StartSessionResponse {
  session_id: number
  mode: SessionMode
  words: Word[]
}

export const reviewApi = {
  start: (mode: SessionMode, group_id: number | null, limit = 20) =>
    request<StartSessionResponse>('/api/v1/review/sessions', {
      method: 'POST',
      body: JSON.stringify({ mode, group_id, limit }),
    }),
  answer: (sessionId: number, word_id: number, outcome: ReviewOutcome, response_time_ms?: number) =>
    request<{ word: Word; was_new_word_learned: boolean }>(`/api/v1/review/sessions/${sessionId}/answers`, {
      method: 'POST',
      body: JSON.stringify({ word_id, outcome, response_time_ms }),
    }),
  complete: (sessionId: number, new_words_learned_count: number) =>
    request<SessionSummary>(`/api/v1/review/sessions/${sessionId}/complete`, {
      method: 'POST',
      body: JSON.stringify({ new_words_learned_count }),
    }),
  weeklyProgress: () => request<{ counts_by_day: Record<string, number> }>('/api/v1/review/weekly-progress'),
}

// --- MnemoLab ----------------------------------------------------------------

/** Mirrors the backend's discriminated suggestion response: the endpoint
 *  answers 200 in all three cases, because an AI provider being switched off
 *  or temporarily unreachable is a state of a healthy install, not an error. */
export type MnemonicSuggestion =
  | { status: 'disabled' }
  | { status: 'unavailable'; detail: string }
  | { status: 'ok'; text: string }

export const mnemonicsApi = {
  list: (wordId: number) => request<MnemonicNote[]>(`/api/v1/words/${wordId}/mnemonics`),
  suggest: (wordId: number) =>
    request<MnemonicSuggestion>(`/api/v1/words/${wordId}/mnemonics/suggest`, { method: 'POST' }),
  add: (wordId: number, text: string) =>
    request<MnemonicNote>(`/api/v1/words/${wordId}/mnemonics`, { method: 'POST', body: JSON.stringify({ text }) }),
  vote: (wordId: number, mnemonicId: number, upvote: boolean) =>
    request<MnemonicNote>(`/api/v1/words/${wordId}/mnemonics/${mnemonicId}/vote`, {
      method: 'POST',
      body: JSON.stringify({ upvote }),
    }),
}

// --- Settings & Profile -------------------------------------------------

export const settingsApi = {
  getRecallSettings: () => request<RecallSettings>('/api/v1/recall-settings'),
  updateRecallSettings: (settings: RecallSettings) =>
    request<RecallSettings>('/api/v1/recall-settings', { method: 'PUT', body: JSON.stringify(settings) }),
  profile: () => request<ProfileOverview>('/api/v1/profile'),
  weaknesses: () => request<WeaknessProfile>('/api/v1/me/weaknesses'),
  cefrProgress: () => request<CefrProgress>('/api/v1/me/cefr-progress'),
}

export const graphApi = {
  prerequisites: (wordId: number) => request<Prerequisites>(`/api/v1/words/${wordId}/prerequisites`),
  related: (wordId: number, limit = 10) =>
    request<RelatedWord[]>(`/api/v1/words/${wordId}/related?limit=${limit}`),
}

export const practiceApi = {
  dailySession: () => request<DailySession>('/api/v1/practice/daily-session'),
  updateDailySession: (payload: Omit<DailySession, 'due_count'>) =>
    request<DailySession>('/api/v1/practice/daily-session', { method: 'PUT', body: JSON.stringify(payload) }),
  generateExercise: (word_id: number, kind: PracticeExercise['kind'] = 'translation') =>
    request<PracticeExercise>('/api/v1/practice/exercises', { method: 'POST', body: JSON.stringify({ word_id, kind }) }),
  answerExercise: (exerciseId: number, response: string) =>
    request<PracticeExercise>(`/api/v1/practice/exercises/${exerciseId}/answer`, { method: 'POST', body: JSON.stringify({ response }) }),
  pronunciationFeedback: (word_id: number, transcript: string) =>
    request<{ accepted: boolean; feedback: string }>('/api/v1/practice/pronunciation-feedback', { method: 'POST', body: JSON.stringify({ word_id, transcript }) }),
  writingCorrection: (word_id: number, text: string) =>
    request<{ corrected_text: string; feedback: string }>('/api/v1/practice/writing-correction', { method: 'POST', body: JSON.stringify({ word_id, text }) }),
}

export const reportsApi = {
  buildWeekly: () => request<WeeklyLearningReport>('/api/v1/reports/weekly', { method: 'POST' }),
  listWeekly: () => request<WeeklyLearningReport[]>('/api/v1/reports/weekly'),
  getWeekly: (reportId: number) => request<WeeklyLearningReport>(`/api/v1/reports/weekly/${reportId}`),
  generateNarration: (reportId: number) => request<WeeklyLearningReport>(`/api/v1/reports/weekly/${reportId}/narration`, { method: 'POST' }),
}

export const notificationsApi = {
  listPending: () =>
    request<PendingDesktopNotifications>('/api/v1/desktop-notifications'),
  // Idempotent server-side: acknowledging an id twice reports 0 rather than
  // failing, which is what lets the shell acknowledge after showing.
  acknowledge: (notificationIds: number[]) =>
    request<{ acknowledged: number }>('/api/v1/desktop-notifications/ack', {
      method: 'POST',
      body: JSON.stringify({ notification_ids: notificationIds }),
    }),
  // Idempotent server-side. A 409 means the notification expired while it sat
  // in the tray, which is a normal outcome rather than a failure.
  act: (notificationId: number, action: NotificationActionId) =>
    request<NotificationActionResult>(`/api/v1/desktop-notifications/${notificationId}/action`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    }),
}

export const aiSettingsApi = {
  get: () => request<AISettings>('/api/v1/ai-settings'),
  update: (settings: AISettings) =>
    request<AISettings>('/api/v1/ai-settings', { method: 'PUT', body: JSON.stringify(settings) }),
}

// --- Admin ----------------------------------------------------------------

export const adminApi = {
  stats: () => request<AdminStats>('/api/v1/admin/stats'),
  users: (search?: string) =>
    request<{ users: User[]; total: number }>(`/api/v1/admin/users${search ? `?search=${encodeURIComponent(search)}` : ''}`),
  suspend: (userId: number) => request<void>(`/api/v1/admin/users/${userId}/suspend`, { method: 'POST' }),
  reactivate: (userId: number) => request<void>(`/api/v1/admin/users/${userId}/reactivate`, { method: 'POST' }),
  remove: (userId: number) => request<void>(`/api/v1/admin/users/${userId}`, { method: 'DELETE' }),
}
