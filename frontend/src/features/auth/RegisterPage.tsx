import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import { ApiRequestError } from '../../lib/api'
import { Button } from '../../components/ui/Button'
import { Input } from '../../components/ui/Input'
import { Icon } from '../../components/ui/Icon'

export function RegisterPage() {
  const { register } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)

    if (password.length < 8) {
      setError('Password must be at least 8 characters.')
      return
    }
    if (password !== confirmPassword) {
      setError('Passwords do not match.')
      return
    }

    setLoading(true)
    try {
      await register(username, email, password)
      navigate('/onboarding')
    } catch (err) {
      setError(err instanceof ApiRequestError ? err.message : 'Something went wrong. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen w-full items-center justify-center bg-canvas-dark p-4 sm:p-6 lg:p-8">
      <div className="grid w-full max-w-4xl grid-cols-1 overflow-hidden rounded-lg bg-surface shadow-soft md:grid-cols-2">
        <div className="flex flex-col items-center justify-center gap-4 bg-primary p-8 text-center text-ink md:p-12">
          <Icon name="translate" className="text-6xl" />
          <h2 className="font-display text-3xl font-bold">LensWord</h2>
          <p>Expand your world, one word at a time.</p>
        </div>
        <div className="flex flex-col justify-center p-8 sm:p-12">
          <h1 className="font-display text-3xl font-bold text-white">Create your account</h1>
          <p className="pb-6 pt-1 text-white/50">Join LensWord to start your journey.</p>
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <Input label="Username" required minLength={3} value={username} onChange={(e) => setUsername(e.target.value)} placeholder="Enter your username" />
            <Input label="Email address" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="Enter your email" />
            <Input label="Password" type="password" autoComplete="new-password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} placeholder="At least 8 characters" />
            <Input label="Confirm password" type="password" autoComplete="new-password" required value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} placeholder="Confirm your password" />
            {error && <p className="text-sm text-danger">{error}</p>}
            <Button type="submit" size="lg" loading={loading} className="mt-2 w-full">
              Register
            </Button>
          </form>
          <p className="pt-6 text-center text-sm text-white/60">
            Already have an account?{' '}
            <Link to="/login" className="font-medium text-primary hover:underline">
              Log in
            </Link>
          </p>
        </div>
      </div>
    </div>
  )
}
