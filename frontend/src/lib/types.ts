export type SupportedLanguage =
  | 'English' | 'Spanish' | 'French' | 'German' | 'Italian'
  | 'Portuguese' | 'Japanese' | 'Korean' | 'Turkish' | 'Other'

export const LANGUAGES: SupportedLanguage[] = [
  'English', 'Spanish', 'French', 'German', 'Italian',
  'Portuguese', 'Japanese', 'Korean', 'Turkish', 'Other',
]

export type WordStatus = 'new' | 'learning' | 'review' | 'mastered' | 'needs_review'
export type ReviewOutcome = 'correct' | 'incorrect' | 'skipped'
export type SessionMode = 'standard' | 'focus' | 'walking' | 'night' | 'break' | 'mistakes'
export type UserRole = 'user' | 'admin'
export type AIProvider = 'none' | 'ollama'

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
  fsrs_retrievability?: number | null
}

// AI provenance on a card (issue #140).
export type AiState = 'human' | 'unverified' | 'verified'

export interface WordRevision {
  field: string
  // Null means the field had no value before — "the model added this" rather
  // than "the model replaced this".
  before_value: string | null
  after_value: string | null
  source: 'ai' | 'human' | 'bulk'
  changed_at: string
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
  definition: string | null
  part_of_speech: string | null
  cefr_level: string | null
  pronunciation: string | null
  collocations: string[]
  tags: string[]
  ai_confidence: number | null
  ai_provider: string | null
  ai_model: string | null
  ai_verified_at: string | null
  // Derived server-side so the badge cannot disagree with the provenance
  // columns it describes.
  ai_state: AiState
  synonyms: string[]
  antonyms: string[]
  topics: string[]
  review_state: ReviewState
  created_at: string
}

export interface WordEnrichment {
  term: string
  target_language: string
  translations: string[]
  definitions: string[]
  part_of_speech: string | null
  cefr_level: string | null
  pronunciation: string | null
  examples: string[]
  synonyms: string[]
  antonyms: string[]
  collocations: string[]
  tags: string[]
  mnemonic: string | null
  category: string | null
  confidence: number | null
  provider: string
  model: string
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
  scheduler: 'sm2' | 'fsrs'
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
  /** IANA identifier, e.g. 'Europe/Istanbul'. Reminder times and quiet
   *  hours are interpreted in this zone. */
  time_zone: string
}

export interface DailySession {
  enabled: boolean
  goal_minutes: number
  review_limit: number
  due_count: number
}

export interface PracticeExercise {
  id: number
  word_id: number
  kind: 'translation' | 'definition' | 'cloze'
  prompt: string
  options: string[]
  answered: boolean
  correct: boolean | null
}

export interface WeeklyLearningReport {
  id: number
  snapshot: {
    schema_version: number
    week: { start: string; end: string; time_zone: string }
    source_range: { session_count: number; attempt_count: number }
    studied: number
    retained: number
    overdue: number
    difficult_topics: Array<{ name: string; mistakes: number }>
    repeated_mistake_categories: Array<{ name: string; mistakes: number }>
    productive_time_windows: Array<{ label: string; attempts: number }>
    data_completeness: { status: 'complete' | 'sparse'; warnings: string[]; missing_data: string[] }
    generated_at: string
  }
  narration: string | null
  created_at: string
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

export interface AISettings {
  provider: AIProvider
  model: string
  base_url: string
  max_output_tokens: number
  context_max_chars: number
}

/** Mirrors app.domain.value_objects.NotificationAction. */
export type NotificationActionId = 'start_session' | 'remind_later' | 'skip_today'

export interface DesktopNotification {
  id: number
  message: string
  created_at: string
  title: string
  body: string
  /** Empty once the notification has expired, so no dead buttons are drawn. */
  actions: NotificationActionId[]
  expires_at: string | null
}

export interface PendingDesktopNotifications {
  notifications: DesktopNotification[]
  /** True when the page was cut short by the limit, so more are waiting. */
  has_more: boolean
  /** Bumped when the meaning of the payload changes, not when a field is added. */
  payload_version: number
}

export interface NotificationActionResult {
  /** The action that stands — for a duplicate callback, the original one. */
  action: NotificationActionId
  /** False when this notification had already been answered. */
  applied: boolean
  open_review: boolean
}

// Weakness profile (issue #134). Every figure carries the count it came from:
// a share on its own invites reading 60% of five mistakes and 60% of five
// hundred as the same claim.
export interface CategoryWeakness {
  category: string
  occurrences: number
  share: number
}

export interface ConfusedPair {
  word_id: number
  word_term: string | null
  confused_with_word_id: number
  confused_with_term: string | null
  occurrences: number
}

export interface WeaknessProfile {
  total_mistakes: number
  categories: CategoryWeakness[]
  confused_pairs: ConfusedPair[]
  // True when there is not enough history to say anything. Rendered as "not
  // enough evidence yet" rather than an empty list, which would read as "you
  // have no weaknesses".
  insufficient_data: boolean
}

// Knowledge-graph search and CEFR progress (issue #143).
export interface RelatedWord {
  word_id: number
  term: string
  relation: string
  strength: number
  // Why the two are related, in words. A graph that cannot justify an edge is
  // one nobody trusts enough to act on.
  evidence: string
}

export interface Prerequisites {
  word_id: number
  term: string
  cefr_level: string | null
  prerequisites: RelatedWord[]
  // The word's own level is unknown, so no comparison is possible. Different
  // from "nothing easier found", which is a real answer.
  level_unknown: boolean
}

export interface LevelProgress {
  level: string
  total: number
  started: number
  mastered: number
  mastery_share: number
}

export interface CefrProgress {
  levels: LevelProgress[]
  // Words with no level recorded, kept separate so the parts add up.
  unlevelled: LevelProgress | null
  total_words: number
}
