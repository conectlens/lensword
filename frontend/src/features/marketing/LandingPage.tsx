import { Link } from 'react-router-dom'
import { Icon } from '../../components/ui/Icon'
import { Button } from '../../components/ui/Button'

const STEPS = [
  { icon: 'add_circle', title: 'Add or import words', body: 'Easily add new vocabulary you encounter, organized into groups.' },
  { icon: 'psychology', title: 'Daily forced recall', body: 'LensWord prompts you to remember words right before you forget them.' },
  { icon: 'monitoring', title: 'Long-term memory tracking', body: 'Watch your vocabulary move from short-term to long-term memory.' },
]

const FEATURES = [
  { icon: 'update', title: 'Spaced repetition', body: 'An SM-2 based algorithm schedules reviews at increasing intervals for optimal retention.' },
  { icon: 'memory', title: 'Forced Recall Engine', body: 'Actively retrieve words from memory on your terms — morning, idle time, or before sleep.' },
  { icon: 'meeting_room', title: 'Memory palace rooms', body: 'Place words spatially in memory rooms using the method-of-loci technique.' },
  { icon: 'science', title: 'MnemoLab', body: 'Build and share memorable mnemonics for the words that give you trouble.' },
]

export function LandingPage() {
  return (
    <div className="min-h-screen bg-canvas-dark text-white">
      <header className="mx-auto flex max-w-6xl items-center justify-between px-6 py-6">
        <div className="flex items-center gap-2 text-primary">
          <Icon name="translate" className="text-2xl" />
          <span className="font-display text-lg font-bold text-white">LensWord</span>
        </div>
        <div className="flex items-center gap-3">
          <Link to="/login" className="text-sm font-medium text-white/70 hover:text-white">
            Log in
          </Link>
          <Link to="/register">
            <Button size="sm">Get started</Button>
          </Link>
        </div>
      </header>

      <section className="mx-auto flex max-w-3xl flex-col items-center gap-6 px-6 py-20 text-center">
        <h1 className="font-display text-5xl font-black leading-tight tracking-tight md:text-6xl">Learn words that stick.</h1>
        <p className="text-lg text-white/60">
          LensWord forces your brain to recall vocabulary at the right time, every day — using spaced repetition and memory-palace visualization.
        </p>
        <div className="flex gap-4">
          <Link to="/register">
            <Button size="lg">Get started</Button>
          </Link>
          <Link to="/login">
            <Button size="lg" variant="secondary">Log in</Button>
          </Link>
        </div>
      </section>

      <section className="mx-auto max-w-5xl px-6 py-16">
        <h2 className="mb-10 text-center font-display text-3xl font-bold">How it works</h2>
        <div className="grid grid-cols-1 gap-8 md:grid-cols-3">
          {STEPS.map((s, i) => (
            <div key={s.title} className="flex flex-col items-center gap-3 text-center">
              <div className="flex h-14 w-14 items-center justify-center rounded-full bg-primary/20 text-primary">
                <Icon name={s.icon} className="text-2xl" />
              </div>
              <h3 className="font-display font-bold">Step {i + 1}: {s.title}</h3>
              <p className="text-white/50">{s.body}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="mx-auto max-w-5xl px-6 py-16">
        <h2 className="mb-2 text-center font-display text-3xl font-bold">Features designed for effective learning</h2>
        <p className="mb-10 text-center text-white/50">Built on proven memory techniques so you never forget a word.</p>
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
          {FEATURES.map((f) => (
            <div key={f.title} className="flex gap-4 rounded-lg bg-surface p-6">
              <Icon name={f.icon} className="text-2xl text-primary" />
              <div>
                <h3 className="font-display font-bold text-white">{f.title}</h3>
                <p className="mt-1 text-white/50">{f.body}</p>
              </div>
            </div>
          ))}
        </div>
      </section>

      <footer className="border-t border-white/10 py-8 text-center text-sm text-white/30">
        © {new Date().getFullYear()} LensWord. Built to help you remember.
      </footer>
    </div>
  )
}
