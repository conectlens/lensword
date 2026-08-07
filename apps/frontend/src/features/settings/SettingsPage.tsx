import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import { aiSettingsApi, ApiRequestError, groupsApi, mcpOauthApi, practiceApi, settingsApi, syncApi } from '../../lib/api'
import { QUEUE_CHANGED_EVENT, queueLength } from '../../lib/offlineQueue'
import { OllamaSetupCheck } from './OllamaSetupCheck'
import type { AISettings, DailySession, Group, McpConnection, RecallSettings, SyncConflict } from '../../lib/types'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Icon } from '../../components/ui/Icon'
import { Spinner } from '../../components/ui/Spinner'
import { Toggle } from '../../components/ui/Toggle'
import { connectMcpServer, deleteMcpServer, disconnectMcpServer, isMcpDesktopAvailable, listMcpServers, saveMcpServer } from '../../lib/mcpClient'
import type { McpServer, McpServerSave } from '../../lib/mcpClient'
import { captureClipboard, clipboardStatus, configureClipboard, isClipboardDesktopAvailable } from '../../lib/clipboardCapture'
import type { ClipboardCapture, ClipboardConfig } from '../../lib/clipboardCapture'
import { autostartStatus, isAutostartDesktopAvailable, setAutostartEnabled } from '../../lib/autostart'
import { captureSelectedText, configureSelectionCapture, isSelectionCaptureDesktopAvailable, selectionCaptureStatus } from '../../lib/selectionCapture'
import type { SelectionCapture, SelectionCaptureStatus } from '../../lib/selectionCapture'

const INTENSITY_LABELS = ['', 'Gentle', 'Light', 'Balanced', 'Firm', 'Intense']

export function SettingsPage() {
  const { user } = useAuth()
  const [settings, setSettings] = useState<RecallSettings | null>(null)
  const [saved, setSaved] = useState(false)
  const [aiSettings, setAiSettings] = useState<AISettings | null>(null)
  const [dailySession, setDailySession] = useState<DailySession | null>(null)

  useEffect(() => {
    settingsApi.getRecallSettings().then(setSettings)
    practiceApi.dailySession().then(setDailySession)
    if (user?.role === 'admin') aiSettingsApi.get().then(setAiSettings).catch(() => setAiSettings(null))
  }, [user?.role])

  async function save(next: RecallSettings) {
    setSettings(next)
    const result = await settingsApi.updateRecallSettings(next)
    setSettings(result)
    setSaved(true)
    setTimeout(() => setSaved(false), 1500)
  }

  function patch(partial: Partial<RecallSettings>) {
    if (!settings) return
    save({ ...settings, ...partial })
  }

  if (!settings) return <Spinner />

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-8">
      <div className="flex items-center justify-between">
        <h1 className="font-display text-3xl font-bold text-white">Settings</h1>
        {saved && <span className="text-sm text-success">Saved</span>}
      </div>

      <Card className="p-6">
        <h2 className="mb-4 font-display text-lg font-bold text-white">Account</h2>
        <div className="flex items-center justify-between border-b border-white/10 py-3">
          <div className="flex items-center gap-3 text-white/70">
            <Icon name="mail" /> Email
          </div>
          <span className="text-white/50">{user?.email}</span>
        </div>
      </Card>

      {dailySession && <Card className="p-6">
        <div className="flex items-center justify-between">
          <div><h2 className="font-display text-lg font-bold text-white">Daily practice session</h2><p className="text-sm text-white/50">Set a realistic daily target for your adaptive review queue.</p></div>
          <Toggle checked={dailySession.enabled} onChange={async (enabled) => setDailySession(await practiceApi.updateDailySession({ ...dailySession, enabled }))} />
        </div>
        <label className="mt-4 flex flex-col gap-1 text-sm text-white/70">Daily goal (minutes)
          <input aria-label="Daily goal minutes" type="number" min={1} max={180} value={dailySession.goal_minutes} onChange={async (event) => setDailySession(await practiceApi.updateDailySession({ ...dailySession, goal_minutes: Number(event.target.value) }))} className="rounded-lg bg-white/5 px-3 py-2 text-white" />
        </label>
        <label className="mt-4 flex flex-col gap-1 text-sm text-white/70">Daily review limit
          <input aria-label="Daily review limit" type="number" min={1} max={100} value={dailySession.review_limit} onChange={async (event) => setDailySession(await practiceApi.updateDailySession({ ...dailySession, review_limit: Number(event.target.value) }))} className="rounded-lg bg-white/5 px-3 py-2 text-white" />
        </label>
      </Card>}

      {user?.role === 'admin' && aiSettings && (
        <AISettingsCard
          settings={aiSettings}
          onSave={async (next) => setAiSettings(await aiSettingsApi.update(next))}
        />
      )}

      <McpServersCard />
      <RemoteCompanionsCard />
      <SelectedTextCaptureCard />
      <ClipboardCaptureCard />
      <AutostartCard />
      <OfflineSyncCard />

      <Card className="p-6">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="font-display text-lg font-bold text-white">Forced Recall Engine</h2>
            <p className="text-sm text-white/50">Interrupts you with micro-questions to strengthen retention.</p>
          </div>
          <Toggle checked={settings.enabled} onChange={(enabled) => patch({ enabled })} />
        </div>

        <div className="mb-6">
          <p className="mb-2 text-sm font-medium text-white">Intensity — {INTENSITY_LABELS[settings.intensity]}</p>
          <input
            type="range"
            min={1}
            max={5}
            value={settings.intensity}
            onChange={(e) => patch({ intensity: Number(e.target.value) })}
            className="w-full accent-primary"
          />
          <div className="mt-1 flex justify-between text-xs text-white/40">
            <span>Gentle</span>
            <span>Intense</span>
          </div>
        </div>

        <label className="mb-4 flex flex-col gap-1 text-sm text-white/70">
          Review scheduler
          <select
            aria-label="Review scheduler"
            value={settings.scheduler}
            onChange={(event) => patch({ scheduler: event.target.value as RecallSettings['scheduler'] })}
            className="rounded-lg bg-white/5 px-3 py-2 text-white"
          >
            <option value="sm2">SM-2 (classic)</option>
            <option value="fsrs">FSRS (adaptive)</option>
          </select>
          <span className="text-xs text-white/40">FSRS schedules each next review from its estimated retrievability.</span>
        </label>

        <div className="flex flex-col divide-y divide-white/10">
          <ToggleRow
            icon="wb_sunny"
            title="Morning check-in"
            description="Kickstart your day with a quick review."
            checked={settings.morning_checkin_enabled}
            onChange={(v) => patch({ morning_checkin_enabled: v })}
          />
          <ToggleRow
            icon="hourglass_empty"
            title="Idle time"
            description="Recalls when you seem to be taking a break."
            checked={settings.idle_time_enabled}
            onChange={(v) => patch({ idle_time_enabled: v })}
          />
          <ToggleRow
            icon="directions_walk"
            title="Walking mode"
            description="Multiple-choice recalls while you're on the move."
            checked={settings.walking_mode_enabled}
            onChange={(v) => patch({ walking_mode_enabled: v })}
          />
          <ToggleRow
            icon="school"
            title="Study breaks"
            description="Review words between study sessions."
            checked={settings.study_breaks_enabled}
            onChange={(v) => patch({ study_breaks_enabled: v })}
          />
          <ToggleRow
            icon="bedtime"
            title="Night wind-down"
            description="A final, gentle recall before sleep."
            checked={settings.night_winddown_enabled}
            onChange={(v) => patch({ night_winddown_enabled: v })}
          />
          <ToggleRow
            icon="auto_awesome"
            title="Graduated acquisition loop"
            description="A short same-day loop to stabilize a word right after you get it wrong, before it goes back to spaced repetition."
            checked={settings.acquisition_loop_enabled}
            onChange={(v) => patch({ acquisition_loop_enabled: v })}
          />
        </div>
      </Card>

      <Card className="p-6">
        <h2 className="mb-4 font-display text-lg font-bold text-white">Notifications</h2>
        <p className="mb-4 text-sm text-white/40">
          These preferences are saved, but actual push/email/desktop delivery isn&apos;t wired to a notification provider in this build —
          see the README.
        </p>
        <div className="flex flex-col divide-y divide-white/10">
          <ToggleRow icon="phone_iphone" title="Mobile push" description="" checked={settings.push_enabled} onChange={(v) => patch({ push_enabled: v })} />
          <ToggleRow icon="mail" title="Email summary" description="" checked={settings.email_enabled} onChange={(v) => patch({ email_enabled: v })} />
          <ToggleRow icon="desktop_windows" title="Desktop browser" description="" checked={settings.desktop_enabled} onChange={(v) => patch({ desktop_enabled: v })} />
          <ToggleRow icon="notifications_active" title="In-app popups" description="" checked={settings.in_app_enabled} onChange={(v) => patch({ in_app_enabled: v })} />
        </div>
      </Card>

      <Card className="p-6">
        <h2 className="mb-4 font-display text-lg font-bold text-white">Time zone</h2>
        <p className="mb-4 text-sm text-white/40">
          Reminder times and quiet hours are read on this clock. Set it to where you actually are, or reminders arrive at the
          wrong hour.
        </p>
        <TimeZoneSelect value={settings.time_zone} onChange={(v) => patch({ time_zone: v })} />
      </Card>
    </div>
  )
}
function SelectedTextCaptureCard() {
  const desktop = isSelectionCaptureDesktopAvailable();
  const navigate = useNavigate();
  const [status, setStatus] = useState<SelectionCaptureStatus | null>(null);
  const [candidate, setCandidate] = useState<SelectionCapture | null>(null);
  const [groups, setGroups] = useState<Group[]>([]);
  const [groupId, setGroupId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function readSelection() {
    try {
      setError(null);
      setCandidate(await captureSelectedText());
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Selected text could not be captured.",
      );
    }
  }
  useEffect(() => {
    if (!desktop) return;
    void selectionCaptureStatus()
      .then(setStatus)
      .catch((err) =>
        setError(
          err instanceof Error
            ? err.message
            : "Selected-text capture is unavailable.",
        ),
      );
    void groupsApi.list().then((next) => {
      setGroups(next);
      setGroupId((current) => current || String(next[0]?.id ?? ""));
    });
    let unlisten: (() => void) | undefined;
    void import("@tauri-apps/api/event").then(({ listen }) =>
      listen("selection-capture-requested", () => {
        void readSelection();
      }).then((stop) => {
        unlisten = stop;
      }),
    );
    return () => unlisten?.();
    // The native event handler deliberately calls the latest capture command; it does not carry text in the event.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [desktop]);
  if (!desktop || !status) return null;
  async function configure(next: { enabled: boolean; shortcut: string }) {
    try {
      setError(null);
      await configureSelectionCapture(next);
      setStatus(await selectionCaptureStatus());
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "The shortcut is already in use or invalid.",
      );
    }
  }
  const selectedGroup = groups.find((group) => group.id === Number(groupId));
  const candidateText = candidate?.text?.trim() ?? "";
  function openWordForm() {
    if (!selectedGroup || !candidateText) return;
    const params = new URLSearchParams({
      term: candidateText.split(/\s+/)[0],
      context: candidateText,
    });
    navigate(`/groups/${selectedGroup.id}/words/new?${params}`);
    setCandidate(null);
  }
  return (
    <Card className="p-6">
      <h2 className="font-display text-lg font-bold text-white">
        Selected-text capture
      </h2>
      <p className="mt-1 text-sm text-white/50">
        Press the configured global shortcut to request the current selection.
        The candidate is held only in this screen until you explicitly review or
        save it.
      </p>
      <div className="mt-4 flex flex-wrap items-end gap-3">
        <label className="text-sm text-white/70">
          Global shortcut
          <input
            aria-label="Selected-text capture shortcut"
            value={status.shortcut}
            onChange={(event) =>
              setStatus({ ...status, shortcut: event.target.value })
            }
            onBlur={() =>
              void configure({
                enabled: status.enabled,
                shortcut: status.shortcut,
              })
            }
            className="ml-2 rounded-lg bg-white/5 px-3 py-2 text-white"
          />
        </label>
        <Button
          onClick={() =>
            void configure({
              enabled: !status.enabled,
              shortcut: status.shortcut,
            })
          }
        >
          {status.enabled ? "Disable shortcut" : "Enable shortcut"}
        </Button>
        <Button disabled={!status.enabled} onClick={() => void readSelection()}>
          Capture copied selection
        </Button>
      </div>
      <p className="mt-3 text-xs text-white/50">
        {status.platform} · {status.capability.replaceAll("_", " ")} · fallback:
        copy text first or paste/type it into the word form.
      </p>
      {status.permissionRequired && (
        <p className="mt-2 text-sm text-amber-200">
          macOS needs Accessibility permission for automatic copy. Grant it in
          System Settings → Privacy & Security → Accessibility, then retry.
        </p>
      )}
      {candidate?.status === "permission_required" && (
        <p className="mt-3 text-sm text-amber-200">
          Accessibility permission was denied. Copy the selection, then use the
          fallback button.
        </p>
      )}
      {candidate?.status === "empty_selection" && (
        <p className="mt-3 text-sm text-amber-200">
          No selection was available. Select text and try again.
        </p>
      )}
      {candidate?.status === "sensitive" && (
        <p className="mt-3 text-sm text-amber-200">
          That text looks sensitive and was discarded.
        </p>
      )}
      {candidateText && (
        <div className="mt-4 rounded-lg border border-white/10 p-3">
          <p className="text-sm text-white/70">
            {candidate?.sourceApplication
              ? `From ${candidate.sourceApplication}`
              : "Copied selection"}{" "}
            · not saved
          </p>
          <p className="mt-2 whitespace-pre-wrap text-white">{candidateText}</p>
          {groups.length > 0 && (
            <label className="mt-3 block text-sm text-white/70">
              Review group
              <select
                aria-label="Selected-text review group"
                value={groupId}
                onChange={(event) => setGroupId(event.target.value)}
                className="ml-2 rounded bg-white/10 p-2 text-white"
              >
                {groups.map((group) => (
                  <option key={group.id} value={group.id}>
                    {group.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          <div className="mt-3 flex flex-wrap gap-2">
            <Button onClick={openWordForm} disabled={!selectedGroup}>
              Explain in context
            </Button>
            <Button onClick={openWordForm} disabled={!selectedGroup}>
              Translate and save
            </Button>
            <Button
              disabled={busy || !selectedGroup}
              onClick={async () => {
                const reviewGroup = selectedGroup;
                if (!reviewGroup) return;
                try {
                  setBusy(true);
                  await groupsApi.addWord(reviewGroup.id, {
                    term: candidateText.split(/\s+/)[0],
                    target_language: reviewGroup.target_language,
                    translations: [],
                    example_sentence: candidateText,
                  });
                  setCandidate(null);
                  navigate("/review");
                } catch (err) {
                  setError(
                    err instanceof Error
                      ? err.message
                      : "Could not add this candidate to review.",
                  );
                } finally {
                  setBusy(false);
                }
              }}
            >
              Add to review list
            </Button>
            <Button onClick={() => setCandidate(null)}>Discard</Button>
          </div>
        </div>
      )}
      {error && (
        <p role="alert" className="mt-3 text-sm text-danger">
          {error}
        </p>
      )}
    </Card>
  );
}

function ClipboardCaptureCard() {
  const desktop = isClipboardDesktopAvailable()
  const [config, setConfig] = useState<ClipboardConfig | null>(null)
  const [capture, setCapture] = useState<ClipboardCapture | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => { if (desktop) void clipboardStatus().then(setConfig).catch((err) => setError(err instanceof Error ? err.message : 'Clipboard status is unavailable.')) }, [desktop])
  if (!desktop || !config) return null
  async function update(next: ClipboardConfig) { try { setError(null); await configureClipboard(next); setConfig(next); if (!next.enabled || next.paused) setCapture(null) } catch (err) { setError(err instanceof Error ? err.message : 'Could not update clipboard capture.') } }
  async function read() { try { setError(null); setCapture(await captureClipboard()) } catch (err) { setError(err instanceof Error ? err.message : 'Clipboard could not be read.') } }
  return <Card className="p-6"><h2 className="font-display text-lg font-bold text-white">Clipboard vocabulary capture</h2><p className="mt-1 text-sm text-white/50">Local-only processing. LensWord reads the clipboard only after you opt in; passwords, tokens, payment cards, duplicates, and blocked apps are discarded before preview.</p><div className="mt-4 flex flex-wrap gap-3"><Button onClick={() => update({ ...config, enabled: !config.enabled })}>{config.enabled ? 'Disable capture' : 'Enable capture'}</Button><Button disabled={!config.enabled} onClick={() => update({ ...config, paused: !config.paused })}>{config.paused ? 'Resume' : 'Pause'}</Button><Button disabled={!config.enabled || config.paused} onClick={read}>Check clipboard</Button></div><p className="mt-3 text-xs text-white/50">Processing: local native adapter · status: {capture?.status ?? (config.paused ? 'paused' : config.enabled ? 'ready' : 'disabled')}</p>{capture?.text && <div className="mt-4 rounded-lg border border-white/10 p-3"><p className="text-sm text-white/70">{capture.kind === 'word' ? 'Word candidate' : 'Text candidate'} — not saved</p><p className="mt-2 whitespace-pre-wrap text-white">{capture.text}</p><div className="mt-3 flex gap-2"><Button onClick={() => setCapture(null)}>Discard</Button><Button onClick={() => { navigator.clipboard.writeText(capture.text ?? ''); setCapture(null) }}>Copy for review</Button></div></div>}{error && <p role="alert" className="mt-3 text-sm text-danger">{error}</p>}</Card>
}

function AutostartCard() {
  const desktop = isAutostartDesktopAvailable()
  const [enabled, setEnabled] = useState<boolean | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => { if (desktop) void autostartStatus().then(setEnabled).catch((err) => setError(err instanceof Error ? err.message : 'Launch-at-login status is unavailable.')) }, [desktop])
  if (!desktop || enabled === null) return null
  async function toggle(next: boolean) {
    try { setError(null); await setAutostartEnabled(next); setEnabled(next) } catch (err) { setError(err instanceof Error ? err.message : 'Could not update launch at login.') }
  }
  return <Card className="p-6"><div className="flex items-center justify-between"><div><h2 className="font-display text-lg font-bold text-white">Launch at login</h2><p className="mt-1 text-sm text-white/50">Starts LensWord in the background when you sign in to this computer, so reminders and the tray keep working without opening it by hand.</p></div><Toggle checked={enabled} onChange={toggle} /></div>{error && <p role="alert" className="mt-3 text-sm text-danger">{error}</p>}</Card>
}

/** Offline edits queued locally (issue #218) and conflicts the server could
 *  not reconcile automatically (issue #90) — read-only here; picking a
 *  version to keep is a further, separable step the issue itself calls out
 *  as not required yet. */
function OfflineSyncCard() {
  // Lazily initialized from the queue itself rather than 0-then-an-effect,
  // so the first render is already correct and the effect below only has
  // to subscribe to *changes*, not also perform the initial read.
  const [pending, setPending] = useState(() => queueLength())
  const [conflicts, setConflicts] = useState<SyncConflict[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    function refreshPending() {
      setPending(queueLength())
    }
    window.addEventListener(QUEUE_CHANGED_EVENT, refreshPending)
    return () => window.removeEventListener(QUEUE_CHANGED_EVENT, refreshPending)
  }, [])

  useEffect(() => {
    syncApi.conflicts().then(setConflicts).catch((err) => setError(err instanceof Error ? err.message : 'Could not load sync conflicts.'))
  }, [])

  if (pending === 0 && conflicts.length === 0 && !error) return null

  return (
    <Card className="p-6">
      <h2 className="font-display text-lg font-bold text-white">Offline changes</h2>
      {pending > 0 && (
        <p className="mt-1 text-sm text-white/50">
          {pending} change{pending === 1 ? '' : 's'} made offline, waiting to sync once you're back online.
        </p>
      )}
      {error && <p role="alert" className="mt-2 text-sm text-danger">{error}</p>}
      {conflicts.length > 0 && (
        <div className="mt-4 flex flex-col gap-2 border-t border-white/10 pt-4">
          <p className="text-sm font-medium text-white">
            {conflicts.length} change{conflicts.length === 1 ? '' : 's'} could not be synced automatically
          </p>
          <p className="text-xs text-white/40">
            Each of these was made against a version of the word that had already changed elsewhere. Nothing was lost — the
            edit below is kept, just not applied.
          </p>
          <div className="mt-2 flex flex-col gap-2">
            {conflicts.map((c) => (
              <div key={c.operation_id} className="rounded-lg border border-white/10 p-3 text-sm">
                <p className="text-white">{c.entity_type} · {c.operation}</p>
                <p className="mt-1 text-xs text-white/50">{c.conflict_reason}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </Card>
  )
}

const EMPTY_MCP_SERVER: McpServerSave = {
  id: '', name: '', command: '', args: [], enabled: true, workspaceRoots: [], allowedTools: [], timeoutMs: 10_000,
}

function McpServersCard() {
  const [servers, setServers] = useState<McpServer[]>([])
  const [draft, setDraft] = useState<McpServerSave>(EMPTY_MCP_SERVER)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const desktop = isMcpDesktopAvailable()

  async function refresh() {
    try { setServers(await listMcpServers()) } catch (err) { setError(err instanceof Error ? err.message : 'Could not load MCP connections.') }
  }
  useEffect(() => { if (desktop) void refresh() }, [desktop]) // eslint-disable-line react-hooks/set-state-in-effect
  if (!desktop) return null

  async function save() {
    try {
      setBusy(true); setError(null)
      await saveMcpServer(draft)
      setDraft(EMPTY_MCP_SERVER)
      await refresh()
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not save the MCP server.') } finally { setBusy(false) }
  }

  async function withServer(action: () => Promise<void>) {
    try { setBusy(true); setError(null); await action(); await refresh() } catch (err) { setError(err instanceof Error ? err.message : 'MCP server operation failed.') } finally { setBusy(false) }
  }

  return <Card className="p-6">
    <h2 className="font-display text-lg font-bold text-white">MCP connections</h2>
    <p className="mt-1 text-sm text-white/50">Local stdio servers run outside the webview. Their definitions and optional credentials are stored in your operating system&apos;s credential store.</p>
    <div className="mt-5 space-y-3">
      {servers.map((server) => <div key={server.id} className="rounded-lg border border-white/10 p-3">
        <div className="flex flex-wrap items-center justify-between gap-2"><div><p className="font-medium text-white">{server.name} <span className="text-xs text-white/40">{server.identity && `· ${server.identity}`}</span></p><p className="text-xs text-white/50">{server.tools.map((tool) => tool.name).join(', ') || 'No approved tools discovered yet'}</p></div><span className={`text-xs ${server.health === 'connected' ? 'text-success' : 'text-white/50'}`}>{server.health}</span></div>
        {server.capabilityChanged && <p className="mt-2 text-xs text-warning">Server capabilities changed; newly discovered tools remain blocked until you explicitly allow them.</p>}
        <div className="mt-3 flex gap-2"><Button disabled={busy || !server.enabled} onClick={() => withServer(() => connectMcpServer(server.id).then(() => undefined))}>{server.health === 'connected' ? 'Reconnect' : 'Connect'}</Button>{server.health === 'connected' && <Button disabled={busy} onClick={() => withServer(() => disconnectMcpServer(server.id))}>Disconnect</Button>}<Button disabled={busy} onClick={() => withServer(() => deleteMcpServer(server.id))}>Remove</Button></div>
      </div>)}
    </div>
    <div className="mt-5 grid gap-3 border-t border-white/10 pt-5 sm:grid-cols-2">
      <label className="text-sm text-white/70">Name<input aria-label="MCP server name" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} className="mt-1 w-full rounded-lg bg-white/5 px-3 py-2 text-white" /></label>
      <label className="text-sm text-white/70">ID<input aria-label="MCP server ID" value={draft.id} onChange={(e) => setDraft({ ...draft, id: e.target.value })} className="mt-1 w-full rounded-lg bg-white/5 px-3 py-2 text-white" /></label>
      <label className="text-sm text-white/70 sm:col-span-2">Command<input aria-label="MCP server command" value={draft.command} onChange={(e) => setDraft({ ...draft, command: e.target.value })} className="mt-1 w-full rounded-lg bg-white/5 px-3 py-2 text-white" /></label>
      <label className="text-sm text-white/70">Arguments (space-separated)<input aria-label="MCP server arguments" value={draft.args.join(' ')} onChange={(e) => setDraft({ ...draft, args: e.target.value.split(/\s+/).filter(Boolean) })} className="mt-1 w-full rounded-lg bg-white/5 px-3 py-2 text-white" /></label>
      <label className="text-sm text-white/70">Allowed tools (comma-separated)<input aria-label="MCP allowed tools" value={draft.allowedTools.join(', ')} onChange={(e) => setDraft({ ...draft, allowedTools: e.target.value.split(',').map((item) => item.trim()).filter(Boolean) })} className="mt-1 w-full rounded-lg bg-white/5 px-3 py-2 text-white" /></label>
      <label className="text-sm text-white/70 sm:col-span-2">Approved workspace roots (comma-separated absolute paths)<input aria-label="MCP workspace roots" value={draft.workspaceRoots.join(', ')} onChange={(e) => setDraft({ ...draft, workspaceRoots: e.target.value.split(',').map((item) => item.trim()).filter(Boolean) })} className="mt-1 w-full rounded-lg bg-white/5 px-3 py-2 text-white" /></label>
      <label className="text-sm text-white/70">Credential (optional)<input aria-label="MCP server credential" type="password" value={draft.credential ?? ''} onChange={(e) => setDraft({ ...draft, credential: e.target.value || undefined })} className="mt-1 w-full rounded-lg bg-white/5 px-3 py-2 text-white" /></label>
      <label className="text-sm text-white/70">Timeout (milliseconds)<input aria-label="MCP timeout" type="number" min={250} max={120000} value={draft.timeoutMs} onChange={(e) => setDraft({ ...draft, timeoutMs: Number(e.target.value) })} className="mt-1 w-full rounded-lg bg-white/5 px-3 py-2 text-white" /></label>
    </div>
    {error && <p role="alert" className="mt-3 text-sm text-danger">{error}</p>}
    <div className="mt-4"><Button disabled={busy} onClick={save}>Save MCP server</Button></div>
  </Card>
}

/** Remote MCP companions this account has completed OAuth with (issue
 *  #196) — a companion running on someone else's infrastructure or in the
 *  cloud, as opposed to `McpServersCard` above, which manages local stdio
 *  servers the desktop shell launches itself and which never leave the
 *  device. The list is empty (and this card renders nothing) both when
 *  there are genuinely no connections and when the backend has remote MCP
 *  turned off — a 404 from `REMOTE_MCP_ENABLED=false` and "you have not
 *  connected anything yet" look the same to a user, which is the correct
 *  behavior: there is nothing actionable to tell them apart. */
function RemoteCompanionsCard() {
  const [connections, setConnections] = useState<McpConnection[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busyClientId, setBusyClientId] = useState<string | null>(null)

  async function refresh() {
    try {
      setConnections(await mcpOauthApi.connections())
    } catch (err) {
      // 404 means remote MCP is disabled on this server, not a real error —
      // treat it the same as "no connections" rather than showing a scary
      // error message for a feature that was never turned on.
      if (err instanceof ApiRequestError && err.status === 404) setConnections([])
      else setError(err instanceof Error ? err.message : 'Could not load remote MCP connections.')
    }
  }

  useEffect(() => { void refresh() }, []) // eslint-disable-line react-hooks/set-state-in-effect

  if (connections === null) return null
  if (connections.length === 0 && !error) return null

  async function revoke(clientId: string) {
    try {
      setBusyClientId(clientId)
      setError(null)
      await mcpOauthApi.revoke(clientId)
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not revoke that connection.')
    } finally {
      setBusyClientId(null)
    }
  }

  return (
    <Card className="p-6">
      <h2 className="font-display text-lg font-bold text-white">Remote companions</h2>
      <p className="mt-1 text-sm text-white/50">
        Companions that authorized themselves through OAuth rather than running on this device. Revoking access here blocks
        every request from that companion immediately.
      </p>
      <div className="mt-4 flex flex-col gap-3">
        {connections.map((connection) => (
          <div key={connection.client_id} className="rounded-lg border border-white/10 p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <p className="font-medium text-white">{connection.client_name}</p>
                <p className="text-xs text-white/50">
                  {connection.scope.split(' ').join(', ')} · workspace {connection.workspace}
                </p>
                <p className="mt-1 text-xs text-white/40">
                  Connected {new Date(connection.created_at).toLocaleString()}
                  {connection.last_used_at ? ` · last used ${new Date(connection.last_used_at).toLocaleString()}` : ' · never used'}
                  {' · '}
                  {connection.active_token_count} active session{connection.active_token_count === 1 ? '' : 's'}
                </p>
              </div>
              <Button disabled={busyClientId === connection.client_id} onClick={() => revoke(connection.client_id)}>
                Revoke access
              </Button>
            </div>
          </div>
        ))}
      </div>
      {error && <p role="alert" className="mt-3 text-sm text-danger">{error}</p>}
    </Card>
  )
}

export function AISettingsCard({ settings, onSave }: { settings: AISettings; onSave: (settings: AISettings) => Promise<void> }) {
  const [draft, setDraft] = useState(settings)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  useEffect(() => setDraft(settings), [settings]) // eslint-disable-line react-hooks/set-state-in-effect

  async function saveAiSettings() {
    if (!draft.model.trim()) return setError('Model is required.')
    try {
      const url = new URL(draft.base_url)
      if (url.protocol !== 'http:' && url.protocol !== 'https:') throw new Error()
    } catch {
      return setError('Base URL must be a valid HTTP or HTTPS URL.')
    }
    if (draft.max_output_tokens <= 0 || draft.context_max_chars <= 0) {
      return setError('Maximum tokens and context length must be greater than zero.')
    }
    try {
      setError(null)
      await onSave(draft)
      setSaved(true)
      setTimeout(() => setSaved(false), 1500)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save AI settings.')
    }
  }

  return (
    <Card className="p-6">
      <h2 className="font-display text-lg font-bold text-white">AI provider</h2>
      <p className="mt-1 text-sm text-white/50">Deployment-wide configuration. Only administrators can change these values.</p>
      <div className="mt-5 grid gap-4 sm:grid-cols-2">
        <label className="flex flex-col gap-1 text-sm text-white/70">Provider
          <select aria-label="AI provider" value={draft.provider} onChange={(e) => setDraft({ ...draft, provider: e.target.value as AISettings['provider'] })} className="rounded-lg bg-white/5 px-3 py-2 text-white">
            <option value="none">Disabled</option>
            <option value="ollama">Ollama</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm text-white/70">Model
          <input aria-label="AI model" value={draft.model} onChange={(e) => setDraft({ ...draft, model: e.target.value })} className="rounded-lg bg-white/5 px-3 py-2 text-white" />
        </label>
        <label className="flex flex-col gap-1 text-sm text-white/70 sm:col-span-2">Base URL
          <input aria-label="AI base URL" value={draft.base_url} onChange={(e) => setDraft({ ...draft, base_url: e.target.value })} className="rounded-lg bg-white/5 px-3 py-2 text-white" />
        </label>
        <label className="flex flex-col gap-1 text-sm text-white/70">Maximum output tokens
          <input aria-label="Maximum output tokens" type="number" min={1} value={draft.max_output_tokens} onChange={(e) => setDraft({ ...draft, max_output_tokens: Number(e.target.value) })} className="rounded-lg bg-white/5 px-3 py-2 text-white" />
        </label>
        <label className="flex flex-col gap-1 text-sm text-white/70">Context length
          <input aria-label="Context length" type="number" min={1} value={draft.context_max_chars} onChange={(e) => setDraft({ ...draft, context_max_chars: Number(e.target.value) })} className="rounded-lg bg-white/5 px-3 py-2 text-white" />
        </label>
      </div>
      {error && <p role="alert" className="mt-3 text-sm text-danger">{error}</p>}
      <div className="mt-5 flex items-center gap-3"><Button onClick={saveAiSettings}>Save AI settings</Button>{saved && <span className="text-sm text-success">Saved</span>}</div>
      {/* Below the save button on purpose: the check reports what the *saved*
          configuration finds, so running it against an unsaved draft would
          report on settings that are not in effect. */}
      <div className="mt-5 border-t border-white/10 pt-5">
        <OllamaSetupCheck />
      </div>
    </Card>
  )
}

/** Detected from the browser, used as the suggestion for an account that has
 *  never chosen one. Falls back to UTC where the API is unavailable. */
function detectedTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
  } catch {
    return 'UTC'
  }
}

function TimeZoneSelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  // Intl.supportedValuesOf is unavailable on older engines; the list then
  // narrows to the values that matter here rather than the control vanishing.
  const zones = useMemo(() => {
    const all =
      typeof Intl.supportedValuesOf === 'function' ? Intl.supportedValuesOf('timeZone') : []
    return Array.from(new Set(['UTC', detectedTimeZone(), value, ...all])).filter(Boolean).sort()
  }, [value])

  const detected = detectedTimeZone()

  return (
    <div className="flex flex-col gap-2">
      <select
        aria-label="Time zone"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-white outline-none focus:border-white/30"
      >
        {zones.map((zone) => (
          <option key={zone} value={zone} className="bg-slate-900">
            {zone}
          </option>
        ))}
      </select>
      {value !== detected && (
        <button
          type="button"
          onClick={() => onChange(detected)}
          className="self-start text-xs text-white/50 underline underline-offset-2 hover:text-white/80"
        >
          Use detected time zone ({detected})
        </button>
      )}
    </div>
  )
}

function ToggleRow({ icon, title, description, checked, onChange }: { icon: string; title: string; description: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className="flex items-center justify-between py-3">
      <div className="flex items-center gap-3">
        <Icon name={icon} className="text-primary" />
        <div>
          <p className="font-medium text-white">{title}</p>
          {description && <p className="text-sm text-white/40">{description}</p>}
        </div>
      </div>
      <Toggle checked={checked} onChange={onChange} />
    </div>
  )
}
