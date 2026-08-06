//! Local scheduler adapter for reminder failover (issue #220, on top of the
//! backend's own #87).
//!
//! The backend already exposes what a local scheduler needs to cooperate
//! without double-firing: `GET /api/v1/reminders/failover-intents` (the
//! account's reminders with a stable `revision`) and
//! `POST /api/v1/reminders/delivery-reports` (report what fired locally; the
//! backend claims those occurrences against the same key its own scheduler
//! uses, per #20, so it will not refire them). None of that was reachable
//! from the desktop shell before this module — this is the first place in
//! this crate that talks to the backend directly rather than only through
//! the webview.
//!
//! The ownership rule this module implements mirrors the backend's own
//! `FailoverPolicy` (`app/domain/services/scheduler_failover.py`) exactly,
//! ported rather than reused since the two run in different languages:
//!
//! - **Backend available or degraded** — the backend owns every occurrence.
//!   Degraded is deliberately treated the same as available: it looks like a
//!   good moment for the shell to take over, and taking over is exactly what
//!   produces a duplicate once the deploy or the rate limit ends.
//! - **Offline** — the shell owns occurrences it can see, because nobody
//!   else will fire them.
//! - **Reconnect** — the shell reports what it delivered while offline, the
//!   backend records those occurrences as already claimed, and neither
//!   re-fires them.
//!
//! A job is registered locally whenever a reminder is enabled, regardless of
//! the shell's current view of backend health — registration is not
//! delivery. A job registered only at the moment connectivity drops would
//! miss any occurrence during the gap; ownership is still decided
//! separately, at fire time, by [`executor_for`].
use std::collections::HashMap;
use std::sync::Mutex;

use chrono::{DateTime, Duration as ChronoDuration, NaiveDateTime, NaiveTime, TimeZone, Utc};
use chrono_tz::Tz;
use serde::{Deserialize, Serialize};
use tauri::AppHandle;

// --- Policy (mirrors app/domain/services/scheduler_failover.py) -----------

/// What the shell currently believes about the server. Reported by
/// [`ConnectivityTracker`] rather than inferred from a single request — a
/// server reachable a moment ago says nothing about a laptop about to lose
/// wifi, and a single dropped request says nothing about a server that is
/// merely slow.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum BackendState {
    Available,
    /// Reachable, but not accepting work — a deploy, a rate limit, an
    /// expired token. Deliberately not `Offline`: the backend will catch up
    /// on its own, and taking over would produce a duplicate when it does.
    Degraded,
    Offline,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Executor {
    Backend,
    Local,
    /// Nobody fires it. Not an error state — it is the correct answer for a
    /// disabled reminder.
    None,
}

/// One reminder, in the form both executors agree on. `reminder_id` is the
/// stable identity and `revision` is the authority: two devices holding
/// different revisions of the same intent are holding the same reminder,
/// and the higher revision is the real one.
#[derive(Clone, Debug, PartialEq, Deserialize)]
pub struct ReminderIntent {
    pub reminder_id: i64,
    pub revision: i64,
    /// "HH:MM" or "HH:MM:SS", see `parse_trigger_time`.
    pub trigger_time: String,
    /// IANA identifier, the account's zone (not per-reminder).
    pub time_zone: String,
    pub enabled: bool,
}

/// A firing the shell carried out while the backend was unreachable. The
/// occurrence key is the same one the backend claims with (#20) — the whole
/// reason reconciliation works: the two executors are naming the same
/// firing rather than describing it in their own terms.
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct DeliveryReport {
    pub reminder_id: i64,
    pub occurrence_key: String,
    pub delivered_at: DateTime<Utc>,
    pub revision: i64,
}

/// Who should fire this reminder right now, given the shell's current view
/// of backend health.
pub fn executor_for(state: BackendState, intent: &ReminderIntent) -> Executor {
    if !intent.enabled {
        return Executor::None;
    }
    match state {
        BackendState::Offline => Executor::Local,
        // AVAILABLE and DEGRADED both stay with the backend — see the
        // module doc comment for why degraded is the case worth stating.
        BackendState::Available | BackendState::Degraded => Executor::Backend,
    }
}

/// Whether the shell should hold a local job for this reminder at all.
/// `state` does not affect the answer — see the module doc comment.
pub fn should_register_locally(intent: &ReminderIntent) -> bool {
    intent.enabled
}

// --- Trigger-time / DST arithmetic (mirrors app/domain/value_objects.py) --

/// Parses a reminder's `trigger_time` field ("HH:MM" or "HH:MM:SS"),
/// mirroring `Reminder.time_of_day` exactly.
pub fn parse_trigger_time(raw: &str) -> Result<NaiveTime, String> {
    let parts: Vec<&str> = raw.split(':').collect();
    if parts.len() != 2 && parts.len() != 3 {
        return Err(format!("trigger time '{raw}' is not HH:MM or HH:MM:SS"));
    }
    let hour: u32 = parts[0]
        .parse()
        .map_err(|_| format!("trigger time '{raw}' is not a valid time of day"))?;
    let minute: u32 = parts[1]
        .parse()
        .map_err(|_| format!("trigger time '{raw}' is not a valid time of day"))?;
    let second: u32 = if parts.len() == 3 {
        parts[2]
            .parse()
            .map_err(|_| format!("trigger time '{raw}' is not a valid time of day"))?
    } else {
        0
    };
    NaiveTime::from_hms_opt(hour, minute, second)
        .ok_or_else(|| format!("trigger time '{raw}' is not a valid time of day"))
}

/// Loads a zone, degrading to UTC rather than erroring — mirrors
/// `zone_for`'s read-path forgiveness: a zone that was valid when a
/// reminder was created can become unrecognized if this build's bundled tz
/// data lags the one the backend validated against, and losing the
/// reminder outright would be worse than evaluating it against UTC.
pub fn zone_for(name: &str) -> Tz {
    name.parse().unwrap_or(chrono_tz::UTC)
}

/// The UTC instant a naive local wall-clock time refers to, in `zone`.
///
/// Mirrors the backend's `resolve_local_time` exactly: the *earliest*
/// instant whose local clock in `zone` reaches `local`.
///
/// - An ordinary time maps to the instant that equals it (`Single`).
/// - A time that occurs twice on a fall-back date maps to the earlier of
///   the two (`Ambiguous`), so a reminder fires once, not twice.
/// - A time that never occurs, on a spring-forward date (`None`), has no
///   instant that equals it, so this returns the earliest instant that
///   *reaches* it — the transition itself, found by scanning forward a
///   minute at a time from `local` until the wall clock resolves normally
///   again. (A DST gap is at most a few hours; this runs at most a few
///   hundred iterations, and only twice a year.) A 02:30 reminder in a
///   02:00 -> 03:00 jump resolves to 03:00, not 03:30 — the reminder is
///   moved, not lost.
pub fn resolve_local_time(local: NaiveDateTime, zone: Tz) -> DateTime<Utc> {
    match zone.from_local_datetime(&local) {
        chrono::LocalResult::Single(dt) => dt.with_timezone(&Utc),
        chrono::LocalResult::Ambiguous(earliest, _latest) => earliest.with_timezone(&Utc),
        chrono::LocalResult::None => {
            let mut probe = local;
            loop {
                probe += ChronoDuration::minutes(1);
                match zone.from_local_datetime(&probe) {
                    chrono::LocalResult::Single(dt) => return dt.with_timezone(&Utc),
                    chrono::LocalResult::Ambiguous(earliest, _) => {
                        return earliest.with_timezone(&Utc)
                    }
                    chrono::LocalResult::None => continue,
                }
            }
        }
    }
}

/// Names the firing a local delivery belongs to, mirroring
/// `job_claims.occurrence_key` exactly — this string round-trips into the
/// backend's own claim table verbatim, so any divergence here would let a
/// duplicate through on reconnect rather than being recognized as the same
/// occurrence the backend already knows about.
///
/// `trigger_time: None` names a one-shot job, where the occurrence is the
/// whole job and the date is enough.
pub fn occurrence_key(local_now: NaiveDateTime, trigger_time: Option<NaiveTime>) -> String {
    let Some(trigger_time) = trigger_time else {
        return "once".to_string();
    };
    // Before today's slot means this is a late delivery of yesterday's,
    // which must claim yesterday's key rather than reserve tomorrow's.
    let day = if local_now.time() < trigger_time {
        local_now.date() - ChronoDuration::days(1)
    } else {
        local_now.date()
    };
    format!(
        "{}T{}",
        day.format("%Y-%m-%d"),
        trigger_time.format("%H:%M:%S")
    )
}

// --- Connectivity ------------------------------------------------------

/// How many *consecutive* failed backend calls it takes before the shell
/// calls itself offline rather than degraded. A couple of blips (a wifi
/// hiccup, one slow response) should not hand ownership to the local
/// scheduler — the backend needs a moment to reassert itself on reconnect
/// either way, and flapping ownership back and forth is worse than a short
/// delay in noticing a real outage. Sustained failure should, and does,
/// after this many attempts in a row.
const OFFLINE_AFTER_CONSECUTIVE_FAILURES: u32 = 3;

/// The shell's own honest running assessment of backend reachability —
/// built from a short history of attempts, not any single one, which is
/// the whole point [`BackendState`] exists to be *reported* rather than
/// derived inline from whatever the most recent call happened to do.
#[derive(Debug, Default)]
pub struct ConnectivityTracker {
    consecutive_failures: u32,
}

impl ConnectivityTracker {
    pub fn on_success(&mut self) {
        self.consecutive_failures = 0;
    }

    pub fn on_failure(&mut self) {
        self.consecutive_failures = self.consecutive_failures.saturating_add(1);
    }

    pub fn state(&self) -> BackendState {
        match self.consecutive_failures {
            0 => BackendState::Available,
            n if n < OFFLINE_AFTER_CONSECUTIVE_FAILURES => BackendState::Degraded,
            _ => BackendState::Offline,
        }
    }
}

// --- Scheduler adapter ---------------------------------------------------

struct RegisteredJob {
    intent: ReminderIntent,
    /// Next UTC instant this job is due. Recomputed after every firing (or
    /// re-registration at a newer revision) rather than stored once, so a
    /// `time_zone` edit or a DST transition is picked up on the very next
    /// tick rather than requiring the job to be dropped and re-added.
    next_due_at: DateTime<Utc>,
}

/// Holds every reminder the shell might have to fire locally, and decides,
/// tick by tick, whether it actually should.
///
/// The intents contract carries no recurrence field (only `trigger_time`) —
/// deliberately, per the API schema: this adapter always treats a
/// registered job as recurring daily, and relies on the next intents
/// refresh to drop a job whose reminder has since been disabled or deleted
/// server-side (a one-shot reminder that already fired). Recomputing
/// "tomorrow, same trigger_time" for something that turns out not to recur
/// is harmless — the next sync removes it before it would ever fire again.
#[derive(Default)]
pub struct SchedulerAdapter {
    jobs: HashMap<i64, RegisteredJob>,
}

impl SchedulerAdapter {
    /// Registers, updates or drops local jobs to match the account's
    /// current intents. Call on every successful intents fetch.
    pub fn sync_intents(&mut self, intents: Vec<ReminderIntent>, now: DateTime<Utc>) {
        let mut seen = std::collections::HashSet::new();
        for intent in intents {
            seen.insert(intent.reminder_id);
            if !should_register_locally(&intent) {
                self.jobs.remove(&intent.reminder_id);
                continue;
            }
            let needs_recompute = match self.jobs.get(&intent.reminder_id) {
                None => true,
                // A strictly newer revision means the schedule may have
                // changed; anything else (same or, defensively, an
                // out-of-order older revision) leaves the existing
                // next_due_at alone rather than resetting a job that may be
                // about to fire.
                Some(existing) => intent.revision > existing.intent.revision,
            };
            if needs_recompute {
                if let Some(next_due_at) = Self::next_due_at(&intent, now) {
                    self.jobs.insert(
                        intent.reminder_id,
                        RegisteredJob {
                            intent,
                            next_due_at,
                        },
                    );
                }
            }
        }
        // Drop jobs for reminders no longer present at all — deleted, or
        // belonging to an account the shell is no longer signed in as.
        self.jobs.retain(|id, _| seen.contains(id));
    }

    fn next_due_at(intent: &ReminderIntent, after: DateTime<Utc>) -> Option<DateTime<Utc>> {
        let trigger_time = parse_trigger_time(&intent.trigger_time).ok()?;
        let zone = zone_for(&intent.time_zone);
        let local_now = after.with_timezone(&zone).naive_local();
        let mut candidate_date = local_now.date();
        if local_now.time() >= trigger_time {
            candidate_date = candidate_date.succ_opt()?;
        }
        Some(resolve_local_time(
            candidate_date.and_time(trigger_time),
            zone,
        ))
    }

    /// Checks every registered job against `now` and fires the ones that
    /// are both due and, per [`executor_for`] under the shell's current
    /// `state`, the shell's to fire. Returns the delivery reports for
    /// whatever fired locally this tick, for the caller to queue and
    /// submit — this method never talks to the network itself.
    ///
    /// A job that is due but owned by the backend (state is available or
    /// degraded) is not fired — the backend already has or will handle it
    /// — but its `next_due_at` still advances, so a briefly-stale local
    /// clock does not re-evaluate the same occurrence every tick forever.
    pub fn tick(
        &mut self,
        now: DateTime<Utc>,
        state: BackendState,
        notifier: &dyn Notifier,
    ) -> Vec<DeliveryReport> {
        let mut fired = Vec::new();
        for job in self.jobs.values_mut() {
            if job.next_due_at > now {
                continue;
            }
            if executor_for(state, &job.intent) == Executor::Local {
                notifier.notify(
                    "Time to review",
                    "A reminder came due while LensWord's backend was unreachable.",
                );
                let zone = zone_for(&job.intent.time_zone);
                let local_now = now.with_timezone(&zone).naive_local();
                let trigger_time = parse_trigger_time(&job.intent.trigger_time).ok();
                fired.push(DeliveryReport {
                    reminder_id: job.intent.reminder_id,
                    occurrence_key: occurrence_key(local_now, trigger_time),
                    delivered_at: now,
                    revision: job.intent.revision,
                });
            }
            if let Some(next_due_at) = Self::next_due_at(&job.intent, now) {
                job.next_due_at = next_due_at;
            }
        }
        fired
    }

    #[cfg(test)]
    fn registered_ids(&self) -> std::collections::HashSet<i64> {
        self.jobs.keys().copied().collect()
    }
}

// --- Notifier -------------------------------------------------------------

/// Shows the native "a reminder fired locally" toast. A trait so
/// [`SchedulerAdapter::tick`] can be tested without a running Tauri app.
pub trait Notifier {
    fn notify(&self, title: &str, body: &str);
}

pub struct TauriNotifier {
    app: AppHandle,
}

impl TauriNotifier {
    pub fn new(app: AppHandle) -> Self {
        Self { app }
    }
}

impl Notifier for TauriNotifier {
    fn notify(&self, title: &str, body: &str) {
        use tauri_plugin_notification::NotificationExt;
        if let Err(err) = self
            .app
            .notification()
            .builder()
            .title(title)
            .body(body)
            .show()
        {
            log::warn!("failed to show a locally-fired reminder notification: {err}");
        }
    }
}

// --- Backend client ---------------------------------------------------

#[derive(Debug)]
pub enum BackendError {
    /// No token in the credential store — not a connectivity problem, and
    /// deliberately not fed into [`ConnectivityTracker`]: an account that
    /// has never logged in, or just logged out, is not "the backend is
    /// down".
    NotAuthenticated,
    Network(String),
}

impl std::fmt::Display for BackendError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::NotAuthenticated => write!(f, "not authenticated"),
            Self::Network(detail) => write!(f, "{detail}"),
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct DeliveryReportResult {
    pub reminder_id: i64,
    pub occurrence_key: String,
    pub accepted: bool,
    pub reason: Option<String>,
}

/// The two calls this adapter needs from the backend, as a trait so
/// `run_loop` can be exercised against an in-memory fake rather than a real
/// HTTP server — the same dependency-injection seam the backend's own
/// scheduler code uses for its clock and dispatch callable.
pub trait BackendClient {
    fn fetch_intents(
        &self,
    ) -> impl std::future::Future<Output = Result<Vec<ReminderIntent>, BackendError>> + Send;
    fn submit_reports(
        &self,
        reports: &[DeliveryReport],
    ) -> impl std::future::Future<Output = Result<Vec<DeliveryReportResult>, BackendError>> + Send;
}

#[derive(Deserialize)]
struct IntentsResponse {
    intents: Vec<ReminderIntent>,
}

#[derive(Serialize)]
struct DeliveryReportRequest<'a> {
    reminder_id: i64,
    occurrence_key: &'a str,
    delivered_at: DateTime<Utc>,
    revision: i64,
}

#[derive(Serialize)]
struct SubmitDeliveryReportsRequest<'a> {
    reports: Vec<DeliveryReportRequest<'a>>,
}

#[derive(Deserialize)]
struct DeliveryReportResultWire {
    reminder_id: i64,
    occurrence_key: String,
    accepted: bool,
    reason: Option<String>,
}

#[derive(Deserialize)]
struct SubmitDeliveryReportsResponse {
    results: Vec<DeliveryReportResultWire>,
}

pub struct ReqwestBackendClient {
    app: AppHandle,
    http: reqwest::Client,
}

impl ReqwestBackendClient {
    pub fn new(app: AppHandle) -> Self {
        Self {
            app,
            http: reqwest::Client::new(),
        }
    }

    fn resolve_base_url(&self) -> Result<String, BackendError> {
        let from_env = std::env::var(crate::API_BASE_ENV).ok();
        let from_file = crate::config_file_contents(&self.app).map_err(BackendError::Network)?;
        lensword_api_config::resolve(from_env.as_deref(), from_file.as_deref())
            .map(|resolved| resolved.base_url)
            .map_err(|err| BackendError::Network(err.to_string()))
    }

    fn token(&self) -> Result<String, BackendError> {
        match crate::credential::token().map_err(BackendError::Network)? {
            Some(token) => Ok(token),
            None => Err(BackendError::NotAuthenticated),
        }
    }
}

impl BackendClient for ReqwestBackendClient {
    async fn fetch_intents(&self) -> Result<Vec<ReminderIntent>, BackendError> {
        let base = self.resolve_base_url()?;
        let token = self.token()?;
        let response = self
            .http
            .get(format!("{base}/api/v1/reminders/failover-intents"))
            .bearer_auth(token)
            .send()
            .await
            .map_err(|err| BackendError::Network(err.to_string()))?
            .error_for_status()
            .map_err(|err| BackendError::Network(err.to_string()))?;
        let body: IntentsResponse = response
            .json()
            .await
            .map_err(|err| BackendError::Network(err.to_string()))?;
        Ok(body.intents)
    }

    async fn submit_reports(
        &self,
        reports: &[DeliveryReport],
    ) -> Result<Vec<DeliveryReportResult>, BackendError> {
        let base = self.resolve_base_url()?;
        let token = self.token()?;
        let payload = SubmitDeliveryReportsRequest {
            reports: reports
                .iter()
                .map(|r| DeliveryReportRequest {
                    reminder_id: r.reminder_id,
                    occurrence_key: &r.occurrence_key,
                    delivered_at: r.delivered_at,
                    revision: r.revision,
                })
                .collect(),
        };
        let response = self
            .http
            .post(format!("{base}/api/v1/reminders/delivery-reports"))
            .bearer_auth(token)
            .json(&payload)
            .send()
            .await
            .map_err(|err| BackendError::Network(err.to_string()))?
            .error_for_status()
            .map_err(|err| BackendError::Network(err.to_string()))?;
        let body: SubmitDeliveryReportsResponse = response
            .json()
            .await
            .map_err(|err| BackendError::Network(err.to_string()))?;
        Ok(body
            .results
            .into_iter()
            .map(|r| DeliveryReportResult {
                reminder_id: r.reminder_id,
                occurrence_key: r.occurrence_key,
                accepted: r.accepted,
                reason: r.reason,
            })
            .collect())
    }
}

// --- The loop --------------------------------------------------------

/// Runs forever: on every tick, refresh intents (on success, resync the
/// local job set and mark the backend reachable; on failure, mark a
/// failure and keep the existing job set — the backend being briefly
/// unreachable is not a reason to drop reminders it already told the
/// shell about), evaluate every registered job against the shell's
/// current view of backend health, and — if anything fired locally this
/// tick or is still pending from an earlier one — try to submit
/// accumulated delivery reports. A superseded report (the reminder was
/// edited or deleted on another device while this one fired the old
/// occurrence) is logged and dropped rather than retried: retrying would
/// not change the outcome, since the server has already made its decision
/// for that report.
pub async fn run_loop(
    client: impl BackendClient,
    notifier: impl Notifier,
    poll_interval: std::time::Duration,
) {
    let mut scheduler = SchedulerAdapter::default();
    let mut connectivity = ConnectivityTracker::default();
    let mut pending_reports: Vec<DeliveryReport> = Vec::new();
    let mut interval = tokio::time::interval(poll_interval);

    loop {
        interval.tick().await;
        let now = Utc::now();

        match client.fetch_intents().await {
            Ok(intents) => {
                connectivity.on_success();
                scheduler.sync_intents(intents, now);
            }
            Err(BackendError::NotAuthenticated) => {
                // Not a connectivity signal — see BackendError's doc comment.
            }
            Err(err) => {
                log::warn!("reminder failover: could not refresh intents: {err}");
                connectivity.on_failure();
            }
        }

        let state = connectivity.state();
        let fired = scheduler.tick(now, state, &notifier);
        pending_reports.extend(fired);

        if pending_reports.is_empty() {
            continue;
        }
        match client.submit_reports(&pending_reports).await {
            Ok(results) => {
                for result in &results {
                    if !result.accepted {
                        log::info!(
                            "reminder failover: delivery report for reminder {} occurrence {} was superseded: {}",
                            result.reminder_id,
                            result.occurrence_key,
                            result.reason.as_deref().unwrap_or("no reason given"),
                        );
                    }
                }
                pending_reports.clear();
            }
            Err(BackendError::NotAuthenticated) => {
                // Nothing to report to; keep the reports queued for when a
                // session exists again.
            }
            Err(err) => {
                log::warn!(
                    "reminder failover: could not submit delivery reports, will retry: {err}"
                );
                connectivity.on_failure();
            }
        }
    }
}

/// Holds the background task's join handle so it can be examined or
/// (in principle, for a future settings toggle) stopped. Not read from
/// today — installed purely so the loop's lifetime is tied to the app
/// rather than detached, matching the other `*State` types this crate
/// manages.
pub struct SchedulerFailoverState(pub Mutex<Option<tauri::async_runtime::JoinHandle<()>>>);

impl Default for SchedulerFailoverState {
    fn default() -> Self {
        Self(Mutex::new(None))
    }
}

/// How often the shell refreshes intents and re-evaluates local jobs.
/// Matches `useDesktopNotifications.ts`'s existing 30s poll interval for
/// the JS-side pending-notification drain, so the two loops surface a
/// missed reminder on a comparable cadence rather than one lagging the
/// other by an unrelated margin.
pub const POLL_INTERVAL: std::time::Duration = std::time::Duration::from_secs(30);

/// Spawns the background loop. Call once from the app's `.setup()`.
pub fn install(app: &AppHandle, state: &SchedulerFailoverState) {
    let client = ReqwestBackendClient::new(app.clone());
    let notifier = TauriNotifier::new(app.clone());
    let handle = tauri::async_runtime::spawn(run_loop(client, notifier, POLL_INTERVAL));
    *state
        .0
        .lock()
        .expect("scheduler failover state mutex poisoned") = Some(handle);
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};

    fn intent(
        reminder_id: i64,
        revision: i64,
        trigger_time: &str,
        enabled: bool,
    ) -> ReminderIntent {
        ReminderIntent {
            reminder_id,
            revision,
            trigger_time: trigger_time.to_string(),
            time_zone: "UTC".to_string(),
            enabled,
        }
    }

    // --- Policy: mirrors test_scheduler_failover.py's own case list -----

    #[test]
    fn degraded_stays_with_the_backend() {
        let i = intent(1, 1, "09:00", true);
        assert_eq!(executor_for(BackendState::Degraded, &i), Executor::Backend);
    }

    #[test]
    fn available_stays_with_the_backend() {
        let i = intent(1, 1, "09:00", true);
        assert_eq!(executor_for(BackendState::Available, &i), Executor::Backend);
    }

    #[test]
    fn offline_hands_ownership_to_the_shell() {
        let i = intent(1, 1, "09:00", true);
        assert_eq!(executor_for(BackendState::Offline, &i), Executor::Local);
    }

    #[test]
    fn disabled_is_none_in_every_state() {
        let i = intent(1, 1, "09:00", false);
        for state in [
            BackendState::Available,
            BackendState::Degraded,
            BackendState::Offline,
        ] {
            assert_eq!(executor_for(state, &i), Executor::None);
        }
    }

    #[test]
    fn a_disabled_reminder_is_never_registered_locally_regardless_of_state() {
        assert!(!should_register_locally(&intent(1, 1, "09:00", false)));
    }

    #[test]
    fn an_enabled_reminder_registers_locally_even_while_the_backend_is_available() {
        // The point of registering ahead of an outage, not only during one.
        assert!(should_register_locally(&intent(1, 1, "09:00", true)));
    }

    // --- Trigger-time parsing ---

    #[test]
    fn trigger_time_accepts_hh_mm_and_hh_mm_ss() {
        assert_eq!(
            parse_trigger_time("09:30").unwrap(),
            NaiveTime::from_hms_opt(9, 30, 0).unwrap()
        );
        assert_eq!(
            parse_trigger_time("09:30:15").unwrap(),
            NaiveTime::from_hms_opt(9, 30, 15).unwrap()
        );
    }

    #[test]
    fn trigger_time_rejects_garbage() {
        assert!(parse_trigger_time("not-a-time").is_err());
        assert!(parse_trigger_time("25:00").is_err());
    }

    // --- occurrence_key: mirrors job_claims.occurrence_key exactly ---

    #[test]
    fn occurrence_key_is_once_for_a_one_shot_reminder() {
        let now =
            NaiveDateTime::parse_from_str("2026-08-06 09:00:00", "%Y-%m-%d %H:%M:%S").unwrap();
        assert_eq!(occurrence_key(now, None), "once");
    }

    #[test]
    fn occurrence_key_uses_todays_date_at_or_after_the_slot() {
        let now =
            NaiveDateTime::parse_from_str("2026-08-06 09:05:00", "%Y-%m-%d %H:%M:%S").unwrap();
        let slot = NaiveTime::from_hms_opt(9, 0, 0).unwrap();
        assert_eq!(occurrence_key(now, Some(slot)), "2026-08-06T09:00:00");
    }

    #[test]
    fn occurrence_key_uses_yesterdays_date_for_a_late_delivery_before_todays_slot() {
        // A late delivery of yesterday's 09:00 slot, discovered at 00:30.
        let now =
            NaiveDateTime::parse_from_str("2026-08-06 00:30:00", "%Y-%m-%d %H:%M:%S").unwrap();
        let slot = NaiveTime::from_hms_opt(9, 0, 0).unwrap();
        assert_eq!(occurrence_key(now, Some(slot)), "2026-08-05T09:00:00");
    }

    // --- resolve_local_time: mirrors value_objects.resolve_local_time ---

    #[test]
    fn an_ordinary_time_resolves_to_the_instant_that_equals_it() {
        let zone = chrono_tz::UTC;
        let local =
            NaiveDateTime::parse_from_str("2026-08-06 09:00:00", "%Y-%m-%d %H:%M:%S").unwrap();
        let resolved = resolve_local_time(local, zone);
        assert_eq!(resolved.naive_utc(), local);
    }

    #[test]
    fn a_fall_back_repeated_time_resolves_to_its_earlier_occurrence() {
        // US Eastern falls back at 2026-11-01 02:00 local (an extra 01:00-02:00
        // hour) — 01:30 happens twice; the earlier UTC instant is the one still
        // on daylight time (EDT, UTC-4).
        let zone: Tz = "America/New_York".parse().unwrap();
        let local =
            NaiveDateTime::parse_from_str("2026-11-01 01:30:00", "%Y-%m-%d %H:%M:%S").unwrap();
        let resolved = resolve_local_time(local, zone);
        let earlier = zone
            .with_ymd_and_hms(2026, 11, 1, 1, 30, 0)
            .earliest()
            .unwrap();
        assert_eq!(resolved, earlier.with_timezone(&Utc));
    }

    #[test]
    fn a_spring_forward_gap_time_resolves_to_the_transition_not_the_naive_offset() {
        // US Eastern springs forward at 2026-03-08 02:00 -> 03:00 local. 02:30
        // never happens; per the docstring's own worked example this resolves
        // to 03:00, not 03:30.
        let zone: Tz = "America/New_York".parse().unwrap();
        let local =
            NaiveDateTime::parse_from_str("2026-03-08 02:30:00", "%Y-%m-%d %H:%M:%S").unwrap();
        let resolved = resolve_local_time(local, zone);
        let expected = zone.with_ymd_and_hms(2026, 3, 8, 3, 0, 0).single().unwrap();
        assert_eq!(resolved, expected.with_timezone(&Utc));
    }

    // --- ConnectivityTracker ---

    #[test]
    fn starts_available_before_any_attempt() {
        let tracker = ConnectivityTracker::default();
        assert_eq!(tracker.state(), BackendState::Available);
    }

    #[test]
    fn a_single_failure_is_degraded_not_offline() {
        let mut tracker = ConnectivityTracker::default();
        tracker.on_failure();
        assert_eq!(tracker.state(), BackendState::Degraded);
    }

    #[test]
    fn sustained_failure_becomes_offline() {
        let mut tracker = ConnectivityTracker::default();
        for _ in 0..OFFLINE_AFTER_CONSECUTIVE_FAILURES {
            tracker.on_failure();
        }
        assert_eq!(tracker.state(), BackendState::Offline);
    }

    #[test]
    fn a_success_resets_the_failure_count() {
        let mut tracker = ConnectivityTracker::default();
        for _ in 0..OFFLINE_AFTER_CONSECUTIVE_FAILURES {
            tracker.on_failure();
        }
        tracker.on_success();
        assert_eq!(tracker.state(), BackendState::Available);
    }

    // --- SchedulerAdapter ---

    struct NullNotifier {
        calls: AtomicUsize,
    }

    impl NullNotifier {
        fn new() -> Self {
            Self {
                calls: AtomicUsize::new(0),
            }
        }
        fn call_count(&self) -> usize {
            self.calls.load(Ordering::SeqCst)
        }
    }

    impl Notifier for NullNotifier {
        fn notify(&self, _title: &str, _body: &str) {
            self.calls.fetch_add(1, Ordering::SeqCst);
        }
    }

    fn utc(y: i32, m: u32, d: u32, h: u32, min: u32) -> DateTime<Utc> {
        Utc.with_ymd_and_hms(y, m, d, h, min, 0).unwrap()
    }

    #[test]
    fn sync_registers_every_enabled_intent() {
        let mut scheduler = SchedulerAdapter::default();
        let now = utc(2026, 8, 6, 8, 0);
        scheduler.sync_intents(
            vec![intent(1, 1, "09:00", true), intent(2, 1, "10:00", true)],
            now,
        );
        assert_eq!(scheduler.registered_ids(), [1, 2].into_iter().collect());
    }

    #[test]
    fn sync_never_registers_a_disabled_intent() {
        let mut scheduler = SchedulerAdapter::default();
        scheduler.sync_intents(vec![intent(1, 1, "09:00", false)], utc(2026, 8, 6, 8, 0));
        assert!(scheduler.registered_ids().is_empty());
    }

    #[test]
    fn sync_drops_a_job_whose_intent_disappeared() {
        let mut scheduler = SchedulerAdapter::default();
        scheduler.sync_intents(vec![intent(1, 1, "09:00", true)], utc(2026, 8, 6, 8, 0));
        scheduler.sync_intents(vec![], utc(2026, 8, 6, 8, 5));
        assert!(scheduler.registered_ids().is_empty());
    }

    #[test]
    fn tick_fires_a_due_job_only_when_the_shell_is_the_executor() {
        let mut scheduler = SchedulerAdapter::default();
        scheduler.sync_intents(vec![intent(1, 1, "09:00", true)], utc(2026, 8, 6, 8, 0));

        let notifier = NullNotifier::new();
        let due = utc(2026, 8, 6, 9, 0);

        let fired = scheduler.tick(due, BackendState::Available, &notifier);
        assert!(
            fired.is_empty(),
            "backend owns this occurrence while available"
        );
        assert_eq!(notifier.call_count(), 0);
    }

    #[test]
    fn tick_fires_locally_when_offline_and_reports_the_right_occurrence_key() {
        let mut scheduler = SchedulerAdapter::default();
        scheduler.sync_intents(vec![intent(42, 3, "09:00", true)], utc(2026, 8, 6, 8, 0));

        let notifier = NullNotifier::new();
        let due = utc(2026, 8, 6, 9, 0);
        let fired = scheduler.tick(due, BackendState::Offline, &notifier);

        assert_eq!(fired.len(), 1);
        assert_eq!(fired[0].reminder_id, 42);
        assert_eq!(fired[0].revision, 3);
        assert_eq!(fired[0].occurrence_key, "2026-08-06T09:00:00");
        assert_eq!(notifier.call_count(), 1);
    }

    #[test]
    fn tick_does_not_refire_the_same_job_on_the_next_call() {
        let mut scheduler = SchedulerAdapter::default();
        scheduler.sync_intents(vec![intent(1, 1, "09:00", true)], utc(2026, 8, 6, 8, 0));

        let notifier = NullNotifier::new();
        let due = utc(2026, 8, 6, 9, 0);
        let first = scheduler.tick(due, BackendState::Offline, &notifier);
        assert_eq!(first.len(), 1);

        // Same instant queried again (e.g. two ticks landing close together)
        // must not fire twice — next_due_at has already advanced to tomorrow.
        let second = scheduler.tick(due, BackendState::Offline, &notifier);
        assert!(second.is_empty());
    }

    #[test]
    fn a_newer_revision_updates_the_registered_intent() {
        let mut scheduler = SchedulerAdapter::default();
        scheduler.sync_intents(vec![intent(1, 1, "09:00", true)], utc(2026, 8, 6, 8, 0));
        // Moved to 18:00 on another device.
        scheduler.sync_intents(vec![intent(1, 2, "18:00", true)], utc(2026, 8, 6, 8, 5));

        let notifier = NullNotifier::new();
        // The old 09:00 slot must not fire any more.
        let fired_at_old_time =
            scheduler.tick(utc(2026, 8, 6, 9, 0), BackendState::Offline, &notifier);
        assert!(fired_at_old_time.is_empty());

        let fired_at_new_time =
            scheduler.tick(utc(2026, 8, 6, 18, 0), BackendState::Offline, &notifier);
        assert_eq!(fired_at_new_time.len(), 1);
    }

    #[test]
    fn an_older_or_equal_revision_does_not_reset_a_pending_job() {
        let mut scheduler = SchedulerAdapter::default();
        scheduler.sync_intents(vec![intent(1, 5, "09:00", true)], utc(2026, 8, 6, 8, 0));
        // A stale re-sync with the same revision must not perturb the job.
        scheduler.sync_intents(vec![intent(1, 5, "09:00", true)], utc(2026, 8, 6, 8, 30));

        let notifier = NullNotifier::new();
        let fired = scheduler.tick(utc(2026, 8, 6, 9, 0), BackendState::Offline, &notifier);
        assert_eq!(fired.len(), 1);
    }
}
