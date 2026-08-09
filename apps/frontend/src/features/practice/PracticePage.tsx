import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { groupsApi, practiceApi } from '../../lib/api'
import type { PracticeExercise, Word } from '../../lib/types'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Spinner } from '../../components/ui/Spinner'
import { Textarea } from '../../components/ui/Textarea'
import { Select } from '../../components/ui/Select'

export function PracticePage() {
  const { groupId } = useParams()
  const [words, setWords] = useState<Word[] | null>(null)
  const [wordId, setWordId] = useState<number | null>(null)
  const [exercise, setExercise] = useState<PracticeExercise | null>(null)
  const [response, setResponse] = useState('')
  const [writing, setWriting] = useState('')
  const [feedback, setFeedback] = useState<string | null>(null)
  const [recording, setRecording] = useState(false)
  const [speechAvailable] = useState(() => 'SpeechRecognition' in window || 'webkitSpeechRecognition' in window)

  useEffect(() => {
    if (!groupId) return
    groupsApi.words(Number(groupId)).then((items) => {
      setWords(items)
      setWordId(items[0]?.id ?? null)
    })
  }, [groupId])

  if (!words) return <Spinner />
  const selected = words.find((word) => word.id === wordId)

  async function generate() {
    if (!wordId) return
    setExercise(await practiceApi.generateExercise(wordId))
    setResponse('')
    setFeedback(null)
  }

  async function answer() {
    if (!exercise) return
    const result = await practiceApi.answerExercise(exercise.id, response)
    setExercise(result)
    setFeedback(result.correct ? 'Correct—nice work.' : 'Not quite. Review the word and try another exercise.')
  }

  async function correctWriting() {
    if (!wordId || !writing.trim()) return
    try {
      const result = await practiceApi.writingCorrection(wordId, writing)
      setWriting(result.corrected_text)
      setFeedback(result.feedback)
    } catch (error) {
      setFeedback(error instanceof Error ? error.message : 'Writing feedback is unavailable.')
    }
  }

  function speak() {
    if (!selected || !('speechSynthesis' in window)) return
    const utterance = new SpeechSynthesisUtterance(selected.term)
    window.speechSynthesis.speak(utterance)
  }

  function recordPronunciation() {
    if (!selected) return
    type Recognition = { lang: string; start: () => void; onresult: (event: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void; onend: () => void }
    type RecognitionWindow = Window & { SpeechRecognition?: new () => Recognition; webkitSpeechRecognition?: new () => Recognition }
    const Constructor = (window as RecognitionWindow).SpeechRecognition ?? (window as RecognitionWindow).webkitSpeechRecognition
    if (!Constructor) return
    const recognition = new Constructor()
    recognition.lang = selected.target_language === 'Spanish' ? 'es-ES' : 'en-US'
    recognition.onresult = async (event) => {
      const transcript = event.results[0][0].transcript
      const result = await practiceApi.pronunciationFeedback(selected.id, transcript)
      setFeedback(`${transcript}: ${result.feedback}`)
    }
    recognition.onend = () => setRecording(false)
    setRecording(true)
    recognition.start()
  }

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6">
      <div><h1 className="font-display text-3xl font-bold text-white">Adaptive practice</h1><p className="text-white/50">Practice each word with targeted exercises and feedback.</p></div>
      <Card className="p-6">
        <label className="flex flex-col gap-2 text-sm text-white/70">Word
          <Select
            size="sm"
            aria-label="Word to practise"
            value={wordId ? String(wordId) : undefined}
            onValueChange={(next) => setWordId(Number(next))}
            options={words.map((word) => ({ value: String(word.id), label: `${word.term} — ${word.translations[0]}` }))}
          />
        </label>
        <div className="mt-4 flex flex-wrap gap-2"><Button onClick={generate} disabled={!wordId}>Generate exercise</Button>{selected && <Button variant="secondary" onClick={speak}>Listen to “{selected.term}”</Button>}{selected && <Button variant="secondary" onClick={recordPronunciation} disabled={!speechAvailable || recording}>{recording ? 'Listening…' : 'Check pronunciation'}</Button>}</div>
        <p className="mt-3 text-xs text-white/40">{speechAvailable ? 'Record your pronunciation for immediate transcript-based feedback.' : 'Speech-to-text is not supported by this browser; listening remains available where supported.'}</p>
      </Card>
      {exercise && <Card className="p-6"><p className="font-display text-lg font-bold text-white">{exercise.prompt}</p><Textarea label="Your answer" value={response} onChange={(event) => setResponse(event.target.value)} rows={2} /><Button className="mt-3" onClick={answer} disabled={!response.trim() || exercise.answered}>Check answer</Button></Card>}
      {selected && <Card className="p-6"><Textarea label={`Write a sentence using “${selected.term}”`} value={writing} onChange={(event) => setWriting(event.target.value)} rows={4} /><Button className="mt-3" variant="secondary" onClick={correctWriting} disabled={!writing.trim()}>Get writing feedback</Button></Card>}
      {feedback && <p role="status" className="rounded-lg bg-primary/10 p-3 text-sm text-white/80">{feedback}</p>}
    </div>
  )
}
