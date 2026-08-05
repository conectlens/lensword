import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'

import { PracticeLabPage } from './PracticeLabPage'
import { ScenarioVocabulary } from './ScenarioVocabulary'
import { conversationsApi, groupsApi, practiceApi, scenariosApi } from '../../lib/api'

vi.mock('../../lib/api', () => ({
  conversationsApi: { send: vi.fn(), start: vi.fn() },
  scenariosApi: { list: vi.fn(), start: vi.fn(), finish: vi.fn(), vocabulary: vi.fn() },
  groupsApi: { list: vi.fn(), words: vi.fn() },
  practiceApi: { writingCorrection: vi.fn(), pronunciationFeedback: vi.fn() },
}))

const vocabulary = vi.mocked(scenariosApi.vocabulary)
const groups = vi.mocked(groupsApi.list)
const words = vi.mocked(groupsApi.words)

const word = (id: number, term: string) => ({
  id,
  term,
  translations: ['x'],
  cefr_level: 'A1',
})

beforeEach(() => {
  vi.mocked(scenariosApi.list).mockResolvedValue([])
  vi.mocked(conversationsApi.start).mockResolvedValue({} as never)
  vi.mocked(practiceApi.writingCorrection).mockReset()
  vocabulary.mockReset()
  groups.mockReset()
  words.mockReset()
  groups.mockResolvedValue([
    { id: 1, name: 'Spanish', target_language: 'Spanish', word_count: 1, due_count: 0, mastered_count: 0 },
  ] as never)
  words.mockResolvedValue([{ id: 5, term: 'camarero' }] as never)
})

describe('PracticeLabPage', () => {
  it('gathers the four modes behind one page', async () => {
    // Someone who wants to practise should not have to know which of four
    // places to go.
    render(<PracticeLabPage />)

    for (const label of ['Conversation', 'Role-play', 'Writing', 'Pronunciation']) {
      expect(await screen.findByRole('button', { name: label })).toBeInTheDocument()
    }
  })

  it('shows one mode at a time rather than hiding the others with CSS', async () => {
    // A conversation left mounted behind another tab would keep its state and
    // its in-flight requests.
    render(<PracticeLabPage />)

    fireEvent.click(screen.getByRole('button', { name: 'Writing' }))

    expect(await screen.findByLabelText('Your sentence')).toBeInTheDocument()
    expect(screen.queryByLabelText('Conversation language')).not.toBeInTheDocument()
  })

  it('says the pronunciation check reads a transcript, not audio', async () => {
    // Told "accepted" after typing the word, a learner would reasonably
    // conclude the feature is fake.
    render(<PracticeLabPage />)
    fireEvent.click(screen.getByRole('button', { name: 'Pronunciation' }))

    expect(await screen.findByText(/checks the transcript, not the sound/)).toBeInTheDocument()
  })
})

describe('ScenarioVocabulary', () => {
  it('shows only words the learner already has', async () => {
    // Suggesting vocabulary they do not have would be a shopping list dressed
    // as preparation.
    vocabulary.mockResolvedValue({
      scenario_key: 'restaurant',
      on_topic: [word(1, 'camarero')],
      related: [word(2, 'mesero')],
      sparse: false,
      detail: '2 word(s) you already know for this situation.',
    })

    render(<ScenarioVocabulary scenarioKey="restaurant" />)

    expect(await screen.findByText('camarero')).toBeInTheDocument()
    expect(screen.getByText('mesero')).toBeInTheDocument()
  })

  it('says a thin deck in words rather than showing a two-item list', async () => {
    vocabulary.mockResolvedValue({
      scenario_key: 'restaurant',
      on_topic: [],
      related: [],
      sparse: true,
      detail: 'You have 0 word(s) for this situation. Add a few before practising.',
    })

    render(<ScenarioVocabulary scenarioKey="restaurant" />)

    expect(await screen.findByText(/Add a few before practising/)).toBeInTheDocument()
  })

  it('names related words separately rather than folding them in', async () => {
    // They came through the knowledge graph, including words the learner
    // confuses with an on-topic one.
    vocabulary.mockResolvedValue({
      scenario_key: 'restaurant',
      on_topic: [word(1, 'camarero')],
      related: [word(2, 'mesero')],
      sparse: false,
      detail: '',
    })

    render(<ScenarioVocabulary scenarioKey="restaurant" />)

    expect(await screen.findByText('Related words')).toBeInTheDocument()
  })

  it('reports a failed load instead of rendering as though there were nothing', async () => {
    vocabulary.mockRejectedValue(new Error('offline'))

    render(<ScenarioVocabulary scenarioKey="restaurant" />)

    expect(await screen.findByText(/Could not load vocabulary/)).toBeInTheDocument()
  })
})
