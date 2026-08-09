import { useEffect, useState, type FormEvent, type KeyboardEvent } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { aiVocabularyApi, groupsApi, wordsApi } from '../../lib/api'
import { queueableRequest } from '../../lib/offlineQueue'
import { LANGUAGES, type Group, type SupportedLanguage } from '../../lib/types'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Icon } from '../../components/ui/Icon'
import { Input } from '../../components/ui/Input'
import { Select } from '../../components/ui/Select'
import { Textarea } from '../../components/ui/Textarea'
import { Spinner } from '../../components/ui/Spinner'

const SUGGESTED_CATEGORIES = ['Travel', 'Work', 'Daily Life', 'Technology', 'Food', 'Emotions']

export function WordFormPage() {
  const { groupId, wordId } = useParams()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const isEditing = Boolean(wordId)

  const [group, setGroup] = useState<Group | null>(null)
  // Only populated when the route named no group (the tray's "Add word"
  // quick action, issue #82) — the picker below lets the user say which one,
  // defaulting to their first once the list loads.
  const [pickableGroups, setPickableGroups] = useState<Group[] | null>(null)
  const [pickedGroupId, setPickedGroupId] = useState<number | null>(null)
  const [term, setTerm] = useState('')
  const [language, setLanguage] = useState<SupportedLanguage>('Spanish')
  const [translations, setTranslations] = useState<string[]>([])
  const [translationDraft, setTranslationDraft] = useState('')
  const [exampleSentence, setExampleSentence] = useState('')
  const [mnemonic, setMnemonic] = useState('')
  const [category, setCategory] = useState('')
  const [contextSentence, setContextSentence] = useState('')
  // What an offline update must name as base_revision to reconcile without
  // a conflict later (issue #218). Irrelevant for a new word.
  const [revision, setRevision] = useState(1)
  const [aiLoading, setAiLoading] = useState(false)
  const [loading, setLoading] = useState(false)
  const [ready, setReady] = useState(!isEditing)

  useEffect(() => {
    if (!isEditing) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setTerm(searchParams.get('term') ?? '')
      setContextSentence(searchParams.get('context') ?? '')
    }
    if (groupId) {
      groupsApi.list().then((all) => setGroup(all.find((g) => g.id === Number(groupId)) ?? null))
    } else if (!isEditing) {
      const hadPickedGroup = pickedGroupId !== null
      groupsApi.list().then((all) => {
        setPickableGroups(all)
        setPickedGroupId((current) => current ?? all[0]?.id ?? null)
        if (!hadPickedGroup && all[0]) setLanguage(all[0].target_language)
      })
    }
    if (isEditing && wordId) {
      wordsApi.get(Number(wordId)).then((w) => {
        setTerm(w.term)
        setLanguage(w.target_language)
        setTranslations(w.translations)
        setExampleSentence(w.example_sentence ?? '')
        setMnemonic(w.mnemonic ?? '')
        setCategory(w.category ?? '')
        setRevision(w.revision)
        setReady(true)
        if (!groupId) groupsApi.list().then((all) => setGroup(all.find((g) => g.id === w.group_id) ?? null))
      })
    } else if (group) {
      setLanguage(group.target_language)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [groupId, wordId, isEditing, searchParams])

  function pickGroup(id: number) {
    setPickedGroupId(id)
    const picked = pickableGroups?.find((g) => g.id === id)
    if (picked) setLanguage(picked.target_language)
  }

  function addTranslation() {
    const value = translationDraft.trim()
    if (value && !translations.includes(value)) setTranslations([...translations, value])
    setTranslationDraft('')
  }

  function handleTranslationKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault()
      addTranslation()
    }
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setLoading(true)
    const payload = {
      term,
      target_language: language,
      translations: translationDraft.trim() ? [...translations, translationDraft.trim()] : translations,
      example_sentence: exampleSentence || null,
      mnemonic: mnemonic || null,
      category: category || null,
    }
    try {
      const targetGroupId = groupId ? Number(groupId) : pickedGroupId
      if (isEditing && wordId) {
        // Offline (issue #218): queued rather than thrown, so the form
        // still navigates away as though the save succeeded — re-fetching
        // the word to learn where to go next would itself fail offline,
        // so navigation uses the group already loaded into state instead
        // of a round trip whose only purpose was naming it.
        await queueableRequest(
          () => wordsApi.update(Number(wordId), payload),
          () => ({
            entity_type: 'word',
            entity_id: Number(wordId),
            operation: 'update',
            payload,
            base_revision: revision,
          }),
        )
        navigate(group ? `/groups/${group.id}` : '/groups')
      } else if (targetGroupId) {
        await queueableRequest(
          () => groupsApi.addWord(targetGroupId, payload),
          () => ({
            entity_type: 'word',
            entity_id: null,
            operation: 'create',
            payload: { group_id: targetGroupId, ...payload },
            base_revision: null,
          }),
        )
        navigate(`/groups/${targetGroupId}`)
      }
    } finally {
      setLoading(false)
    }
  }

  async function translateInContext() {
    if (!term.trim() || !contextSentence.trim()) return
    setAiLoading(true)
    try {
      const enriched = await aiVocabularyApi.translateInContext(term, contextSentence, null, language)
      setTranslations(enriched.translations)
      if (enriched.examples[0]) setExampleSentence(enriched.examples[0])
    } finally { setAiLoading(false) }
  }

  async function regenerate(field: 'example' | 'mnemonic') {
    if (!term.trim()) return
    setAiLoading(true)
    try {
      const result = await aiVocabularyApi.regenerateField(field, term, language)
      if (field === 'example') setExampleSentence(result.value)
      else setMnemonic(result.value)
    } finally { setAiLoading(false) }
  }

  if (!ready) return <Spinner />

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-8">
      <Card className="p-6 sm:p-8">
        <div className="mb-6">
          <h1 className="font-display text-3xl font-bold text-white">{isEditing ? 'Edit word' : 'Add a new word'}</h1>
          <p className="text-white/50">
            {group ? `In ${group.name}` : 'Enter the details for your new vocabulary word below.'}
          </p>
        </div>
        {pickableGroups?.length === 0 && (
          <p className="mb-6 rounded-lg border border-white/10 bg-white/5 p-3 text-sm text-white/70">
            You don&apos;t have a group yet. <Link to="/groups" className="text-primary underline">Create one</Link> before adding a word.
          </p>
        )}
        <form onSubmit={handleSubmit} className="flex flex-col gap-6">
          {pickableGroups !== null && pickableGroups.length > 0 && (
            <Select
              label="Group"
              name="group"
              value={pickedGroupId?.toString() ?? ''}
              onValueChange={(next) => pickGroup(Number(next))}
              options={pickableGroups.map((g) => ({ value: g.id.toString(), label: g.name }))}
            />
          )}
          <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
            <Input label="Word" required value={term} onChange={(e) => setTerm(e.target.value)} placeholder="Enter the word" />
            <Select
              label="Target language"
              value={language}
              onValueChange={(next) => setLanguage(next as SupportedLanguage)}
              options={LANGUAGES.map((l) => ({ value: l, label: l }))}
            />
          </div>

          <div className="flex flex-col gap-2">
            <span className="text-sm font-medium text-white">Translation(s)</span>
            <div className="flex flex-col gap-3 rounded-lg border border-white/10 bg-white/5 p-3">
              {translations.length > 0 && (
                <div className="flex flex-wrap gap-2">
                  {translations.map((t) => (
                    <span key={t} className="flex h-8 items-center gap-2 rounded-full bg-white/10 px-3 text-sm text-white">
                      {t}
                      <button type="button" onClick={() => setTranslations(translations.filter((x) => x !== t))} className="text-white/40 hover:text-white">
                        <Icon name="close" className="text-base" />
                      </button>
                    </span>
                  ))}
                </div>
              )}
              <input
                value={translationDraft}
                onChange={(e) => setTranslationDraft(e.target.value)}
                onKeyDown={handleTranslationKeyDown}
                onBlur={addTranslation}
                placeholder="Type a translation and press Enter"
                className="w-full border-none bg-transparent p-0 text-base text-white placeholder:text-white/30 focus:outline-none focus:ring-0"
              />
            </div>
          </div>

          <div className="flex flex-col gap-2"><Textarea label="Example sentence" rows={3} value={exampleSentence} onChange={(e) => setExampleSentence(e.target.value)} placeholder="Use the word in a sentence" /><Button type="button" variant="ghost" size="sm" loading={aiLoading} onClick={() => regenerate('example')}>Regenerate example</Button></div>

          <div className="flex flex-col gap-2"><Textarea label="Translate in context" rows={2} value={contextSentence} onChange={(e) => setContextSentence(e.target.value)} placeholder="Enter a sentence containing this word" /><Button type="button" variant="secondary" size="sm" loading={aiLoading} disabled={!contextSentence.trim() || !term.trim()} onClick={translateInContext}>Translate in context</Button></div>

          <div className="flex flex-col gap-2">
            <Textarea
              label="Optional: micro-story / mnemonic"
              rows={4}
              value={mnemonic}
              onChange={(e) => setMnemonic(e.target.value)}
              placeholder="Write a short, funny or memorable story using this word."
            />
            <p className="px-1 text-xs text-white/40">Creating a personal story or sentence boosts recall.</p>
            <Button type="button" variant="ghost" size="sm" loading={aiLoading} onClick={() => regenerate('mnemonic')}>Regenerate mnemonic</Button>
          </div>

          <div className="flex flex-col gap-2">
            <span className="text-sm font-medium text-white">Category</span>
            <input
              list="category-suggestions"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              placeholder="Travel, Work, Daily Life..."
              className="h-12 w-full rounded-lg border border-white/10 bg-white/5 px-4 text-base text-white placeholder:text-white/30 focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/40"
            />
            <datalist id="category-suggestions">
              {SUGGESTED_CATEGORIES.map((c) => (
                <option key={c} value={c} />
              ))}
            </datalist>
          </div>

          <div className="flex flex-col-reverse items-center justify-end gap-3 pt-2 sm:flex-row">
            <Button type="button" variant="ghost" onClick={() => navigate(-1)}>
              Cancel
            </Button>
            <Button type="submit" loading={loading} disabled={!term.trim() || (!isEditing && !groupId && !pickedGroupId)}>
              Save word
            </Button>
          </div>
        </form>
      </Card>
    </div>
  )
}
