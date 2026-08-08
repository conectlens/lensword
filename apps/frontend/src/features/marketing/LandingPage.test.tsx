import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { LandingPage } from './LandingPage'

const useAuth = vi.hoisted(() => vi.fn())
vi.mock('../../context/AuthContext', () => ({ useAuth }))

function renderLanding() {
  render(
    <MemoryRouter>
      <LandingPage />
    </MemoryRouter>,
  )
}

describe('LandingPage', () => {
  it('shows Log in / Get started when signed out', () => {
    useAuth.mockReturnValue({ user: null })

    renderLanding()

    expect(screen.getAllByText('Log in').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Get started').length).toBeGreaterThan(0)
    expect(screen.queryByText('Enter Dashboard')).not.toBeInTheDocument()
  })

  it('shows Enter Dashboard instead of auth CTAs when already signed in', () => {
    useAuth.mockReturnValue({ user: { id: 1, username: 'ada', email: 'ada@example.com' } })

    renderLanding()

    expect(screen.getAllByText('Enter Dashboard').length).toBeGreaterThan(0)
    expect(screen.queryByText('Log in')).not.toBeInTheDocument()
    expect(screen.queryByText('Get started')).not.toBeInTheDocument()
  })
})
