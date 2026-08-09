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

export interface AcquisitionState {
  word_id: number
  rung: number
  ladder_version: number
  started_at: string
  updated_at: string
  due_at: string
  graduated: boolean
  entry_reason: string | null
  /** Roughly when this ladder hands back to FSRS — a best-case estimate,
   *  null once graduated. */
  estimated_graduation_at: string | null
}

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
  // What an offline edit must name as base_revision to reconcile without a
  // conflict later (issue #90, issue #218).
  revision: number
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
  topics: string[]
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

/** A remote MCP companion this account has completed OAuth with (issue
 *  #196) — distinct from the local stdio `McpServer` type above, which the
 *  desktop shell manages entirely on-device and never goes through
 *  `/api/v1/mcp/oauth`. */
export interface McpConnection {
  client_id: string
  client_name: string
  scope: string
  workspace: string
  created_at: string
  last_used_at: string | null
  active_token_count: number
}

/** Query params an OAuth client (e.g. Claude.ai) redirects the browser to
 *  this app's /oauth/authorize page with. `workspace` is deliberately
 *  absent — no external client sends it, see McpAuthorizePreview. */
export interface McpAuthorizeRequest {
  response_type: string
  client_id: string
  redirect_uri: string
  code_challenge: string
  code_challenge_method: string
  scope: string
  state: string
}

/** GET /api/v1/mcp/oauth/authorize's response: what to show on the consent
 *  screen. `workspace` is server-resolved (defaulted when the request omitted
 *  it) and must be sent back unchanged on the POST decision below. */
export interface McpAuthorizePreview {
  client_id: string
  client_name: string
  redirect_uri: string
  workspace: string
  scopes: string[]
  already_granted_scopes: string[]
  new_scopes: string[]
}

export interface McpAuthorizeDecision {
  redirect_uri: string
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
  notifications_paused: boolean
  /** Off by default (ADR 0006). Gates every user-visible behavior added by
   *  the Semantic Relatedness phases; no UI reads it yet. */
  semantic_relatedness_enabled: boolean
  /** Off by default (ADR 0007). Independently controllable: deterministic
   *  diagnosis must not require the AI coach. No UI reads these yet. */
  learning_diagnosis_enabled: boolean
  acquisition_loop_enabled: boolean
  ai_coach_enabled: boolean
  /** Off by default. Gates every companion-session route on the backend,
   *  including the in-app chat; the chat surface hides itself when this is
   *  off rather than letting every request 403. */
  ai_companion_enabled: boolean
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

// Bring-Your-Own-Key AI credentials — a user's own Gemini/OpenAI/Vertex AI
// key, used for their own requests since the cloud deployment has no
// billing/credits system to pay for everyone's usage. Mirrors
// app.api.schemas.ai_credentials.UserAICredentialSummary: `details` never
// contains the secret itself, only whichever non-secret fields that
// provider has (Vertex's project_id/location; empty for Gemini/OpenAI,
// which have nothing non-secret in their payload).
export type ByokProvider = 'gemini' | 'openai' | 'vertex'

export interface UserAICredentialSummary {
  provider: ByokProvider
  details: Record<string, string>
  created_at: string
  updated_at: string
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

// Learner-facing observation history and corrections (issue #229 TODO 5).
export type ObservationCorrectionReason = 'misgraded' | 'irrelevant'

export interface ObservationCorrection {
  correction_id: string
  reason: ObservationCorrectionReason
  note: string | null
  created_at: string
}

export interface ObservationHistoryItem {
  observation_id: string
  word_id: number
  // Null for a word that has since been deleted — the observation still
  // happened and still counts as history.
  word_term: string | null
  outcome: ReviewOutcome
  session_mode: SessionMode
  observed_at: string
  attempted_answer: string | null
  modality: string | null
  hint_used: boolean
  // Still shown once set, even though a flagged observation stops being
  // used as diagnosis evidence — the learner needs to see what they
  // already flagged.
  correction: ObservationCorrection | null
}

export interface ObservationHistoryResponse {
  items: ObservationHistoryItem[]
  has_more: boolean
}

// Learning DNA: contextual intervention efficacy, not a learner-style label
// (issue #186). Every estimate carries its own context, sample size, and
// uncertainty interval — there is no global "you are a visual learner"
// verdict anywhere in this shape.
export type EfficacyStatus = 'MEASURED' | 'INCONCLUSIVE' | 'INSUFFICIENT_EVIDENCE'

export interface EfficacyContext {
  item_class: string
  language: string
  prompt_direction: string
  difficulty: string
  modality: string
  horizon_days: number
}

export interface EfficacyEstimate {
  intervention_type: string
  context: EfficacyContext
  status: EfficacyStatus
  intervention_samples: number
  control_samples: number
  intervention_rate: number | null
  control_rate: number | null
  effect: number | null
  interval_low: number | null
  interval_high: number | null
  reason: string | null
  // A ready-to-read sentence with sample size/period/effect/confidence, or
  // null unless status is MEASURED — never a bare percentage.
  recommendation: string | null
  period_start: string | null
  period_end: string | null
  valid_until: string | null
}

// A learner's *stated* modality preference — deliberately its own resource,
// never merged with `EfficacyEstimate` (which is measured, not stated).
export interface ModalityPreference {
  modality: string
  stated_at: string
}

// Offline mutation queue (issue #90's server contract, issue #218's client).
export type SyncEntityType = 'word' | 'review'
export type SyncOperationKind = 'create' | 'update' | 'delete' | 'append'

/** One offline edit, held in local storage until it can be sent. */
export interface QueuedOperation {
  // Client-generated and stable across retries (crypto.randomUUID()) — the
  // same id resubmitted gets the same recorded outcome back rather than
  // being applied twice.
  operation_id: string
  entity_type: SyncEntityType
  // Null for a create: no server id exists until the operation applies.
  entity_id: number | null
  operation: SyncOperationKind
  payload: Record<string, unknown>
  // Required for a reconcilable word update/delete; null for a create or a
  // review append, neither of which can conflict on revision.
  base_revision: number | null
  queued_at: string
}

export interface SyncOperationResult {
  operation_id: string
  status: string
  conflict_reason: string | null
  entity_id: number | null
}

export interface SyncConflict {
  operation_id: string
  entity_type: SyncEntityType
  entity_id: number | null
  operation: SyncOperationKind
  payload: Record<string, unknown>
  base_revision: number | null
  conflict_reason: string | null
  created_at: string
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

// Ollama detection during setup (issue #139). The three failure modes are kept
// distinct because they need different fixes, and a single "AI unavailable"
// says nothing about which one you have.
export interface OllamaProbe {
  reachable: boolean
  // True only when the configured model is actually installed. Reachable is
  // not the same as usable.
  ready: boolean
  models: string[]
  configured_model: string | null
  configured_model_installed: boolean
  recommended_model: string
  // Written server-side so the reason and the advice cannot drift apart.
  detail: string
}

// Learning paths (issue #137). No stored progress: every count below is
// measured from the learner's deck at read time, so the bar can never disagree
// with the vocabulary list beside it.
export interface PathMilestone {
  position: number
  title: string
  description: string
  topic: string
  target_word_count: number
  cefr_level: string | null
  words_held: number
  words_mastered: number
  complete: boolean
  share: number
}

export interface LearningPath {
  id: number
  goal: string
  target_language: string
  group_id: number | null
  ai_provider: string | null
  ai_model: string | null
  created_at: string
  milestones: PathMilestone[]
  completed_count: number
  share: number
  // The first unfinished step. Null when the path is finished.
  next_milestone: PathMilestone | null
}

export interface GeneratePathResult {
  // "ok", "disabled" or "unavailable" — a provider switched off or temporarily
  // down is a normal state of a healthy install, not an error.
  status: string
  path: LearningPath | null
  detail: string | null
}

// Conversation tutor (issue #135).
export type Difficulty = 'gentle' | 'steady' | 'stretch'

export interface Correction {
  // Always a substring of what the learner actually wrote — validated
  // server-side, because a highlight pointing at words nobody typed teaches
  // the learner to ignore highlights entirely.
  original: string
  corrected: string
  explanation: string
}

export interface ConversationMessage {
  id: number
  speaker: 'learner' | 'tutor'
  text: string
  corrections: Correction[]
  created_at: string
}

export interface Conversation {
  id: number
  target_language: string
  difficulty: string
  scenario: string | null
  group_id: number | null
  created_at: string
  ended_at: string | null
  messages: ConversationMessage[]
}

export interface SendMessageResult {
  status: string
  // Present even when the tutor could not answer: losing what someone typed
  // because a model was down is what makes a chat feel broken.
  learner_message: ConversationMessage | null
  tutor_message: ConversationMessage | null
  detail: string | null
}

// Role-play scenarios (issue #136).
export interface Scenario {
  key: string
  title: string
  // What the learner is shown. The tutor's instruction is deliberately not
  // exposed by the API.
  briefing: string
  goals: string[]
  suggested_topics: string[]
}

export interface DimensionScore {
  dimension: string
  score: number
  comment: string
}

export interface ScenarioEvaluation {
  // False when the attempt was too short to judge. Different from a zero,
  // which would claim the learner did badly rather than admit we cannot tell.
  scored: boolean
  scores: DimensionScore[]
  summary: string
  goals_met: string[]
  detail: string
  overall: number | null
}

export interface ScenarioAttempt {
  id: number
  // Turns go through the conversation endpoint — one transport, not two.
  session_id: number
  scenario: Scenario
  started_at: string
  finished_at: string | null
  evaluation: ScenarioEvaluation | null
}

// Scenario preparation vocabulary (issue #144).
export interface ScenarioWord {
  id: number
  term: string
  translations: string[]
  cefr_level: string | null
}

export interface ScenarioVocabulary {
  scenario_key: string
  on_topic: ScenarioWord[]
  // Reached through the knowledge graph rather than topic tags, so a word
  // filed elsewhere but linked to an on-topic one still surfaces.
  related: ScenarioWord[]
  // True when the deck is too thin for a list to be worth showing.
  sparse: boolean
  detail: string
}

// --- Companion chat (issue #343) ----------------------------------------

export type CompanionTurnRole = 'user' | 'assistant'

export type CompanionSessionStatus = 'active' | 'paused' | 'finished' | 'revoked'

export interface CompanionTurn {
  id: number
  session_id: string
  role: CompanionTurnRole
  content: string
  activity_id: string | null
  operation_id: string | null
  created_at: string
}

export interface CompanionSession {
  id: string
  connection_id: string
  client_id: string
  goal: string | null
  language: string | null
  group_id: number | null
  difficulty: string | null
  active_activity: string | null
  summary: string | null
  status: CompanionSessionStatus
  revision: number
  created_at: string
  updated_at: string
  turns: CompanionTurn[]
}

/** Always HTTP 200 with a status, matching the conversation tutor: a
 *  provider switched off or briefly down is a normal state of a healthy
 *  install. `user_turn` is present for every status, so a failed reply
 *  still leaves what was typed on screen. */
export interface CompanionChatResult {
  status: 'ok' | 'disabled' | 'unavailable'
  user_turn: CompanionTurn
  assistant_turn: CompanionTurn | null
  detail: string | null
}
