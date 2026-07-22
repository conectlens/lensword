import type {
  AdminStats, Group, MnemonicNote, ProfileOverview, RecallSettings, Room,
  SessionMode, SessionSummary, SupportedLanguage, User, Word, ReviewOutcome,
} from './types'

const API_BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
const TOKEN_KEY = 'lensword_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string | null): void {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

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

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers })

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

export const mnemonicsApi = {
  list: (wordId: number) => request<MnemonicNote[]>(`/api/v1/words/${wordId}/mnemonics`),
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
