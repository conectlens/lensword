export type SupportedLanguage =
  | 'English' | 'Spanish' | 'French' | 'German' | 'Italian'
  | 'Portuguese' | 'Japanese' | 'Korean' | 'Turkish' | 'Other'

export const LANGUAGES: SupportedLanguage[] = [
  'English', 'Spanish', 'French', 'German', 'Italian',
  'Portuguese', 'Japanese', 'Korean', 'Turkish', 'Other',
]

export type WordStatus = 'new' | 'learning' | 'review' | 'mastered' | 'needs_review'
export type ReviewOutcome = 'correct' | 'incorrect' | 'skipped'
export type SessionMode = 'standard' | 'focus' | 'walking' | 'night' | 'break'
export type UserRole = 'user' | 'admin'

export interface User {
  id: number
  username: string
  email: string
  role: UserRole
  created_at: string
  streak_days: number
  longest_streak_days: number
  last_activity_date: string | null
  total_words_learned: number
  total_study_seconds: number
  is_active: boolean
}

export interface ReviewState {
  strength: number
  ease_factor: number
  interval_days: number
  repetitions: number
  due_at: string
  last_reviewed_at: string | null
  status: WordStatus
}

export interface Word {
  id: number
  group_id: number
  term: string
  target_language: SupportedLanguage
  translations: string[]
  example_sentence: string | null
  mnemonic: string | null
  category: string | null
  synonyms: string[]
  antonyms: string[]
  topics: string[]
  review_state: ReviewState
  created_at: string
}

export interface Group {
  id: number
  name: string
  target_language: SupportedLanguage
  created_at: string
  word_count: number
  mastered_count: number
  due_count: number
  last_reviewed_at: string | null
}

export interface RoomPlacement {
  word_id: number
  x_percent: number
  y_percent: number
  placed_at: string
}

export interface Room {
  id: number
  group_id: number
  name: string
  icon: string
  created_at: string
  placements: RoomPlacement[]
  group_word_count: number
}

export interface MnemonicNote {
  id: number
  word_id: number
  author_id: number
  text: string
  is_ai_generated: boolean
  upvotes: number
  downvotes: number
  score: number
  created_at: string
}

export interface RecallSettings {
  enabled: boolean
  intensity: number
  morning_checkin_enabled: boolean
  idle_time_enabled: boolean
  walking_mode_enabled: boolean
  walking_steps_threshold: number
  study_breaks_enabled: boolean
  study_blocks_before_break: number
  night_winddown_enabled: boolean
  night_start_time: string
  night_end_time: string
  push_enabled: boolean
  email_enabled: boolean
  desktop_enabled: boolean
  in_app_enabled: boolean
  quiet_hours_start: string | null
  quiet_hours_end: string | null
}

export interface Badge {
  code: string
  name: string
  icon: string
  description: string
  earned: boolean
}

export interface ProfileOverview {
  user: User
  badges: Badge[]
}

export interface SessionSummary {
  id: number
  mode: SessionMode
  started_at: string
  ended_at: string | null
  duration_seconds: number
  words_reviewed: number
  correct_count: number
  incorrect_count: number
  new_words_learned: number
  accuracy_percent: number
}

export interface AdminStats {
  total_users: number
  new_users_last_30_days: number
  total_words_learned: number
  active_sessions_last_hour: number
}

export interface ApiError {
  detail: string
}
