import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { GuestOnlyRoute } from './GuestOnlyRoute'

const useAuth = vi.hoisted(() => vi.fn())
vi.mock('../../context/AuthContext', () => ({ useAuth }))

function renderAtLogin() {
  render(
    <MemoryRouter initialEntries={['/login']}>
      <Routes>
        <Route path="/login" element={<GuestOnlyRoute>login form</GuestOnlyRoute>} />
        <Route path="/dashboard" element={<span>dashboard</span>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('GuestOnlyRoute', () => {
  it('shows a spinner while the session is still loading', () => {
    useAuth.mockReturnValue({ user: null, loading: true })

    renderAtLogin()

    expect(screen.queryByText('login form')).not.toBeInTheDocument()
    expect(screen.queryByText('dashboard')).not.toBeInTheDocument()
  })

  it('renders the guest page once loading settles with no session', () => {
    useAuth.mockReturnValue({ user: null, loading: false })

    renderAtLogin()

    expect(screen.getByText('login form')).toBeInTheDocument()
  })

  it('redirects an already-authenticated user to the dashboard', () => {
    useAuth.mockReturnValue({ user: { id: 1, username: 'ada', email: 'ada@example.com' }, loading: false })

    renderAtLogin()

    expect(screen.getByText('dashboard')).toBeInTheDocument()
    expect(screen.queryByText('login form')).not.toBeInTheDocument()
  })
})
