import { afterEach, describe, expect, it, vi } from 'vitest'

import { ROOM_SIZE, clampPercent, floorToPercent, isWebglAvailable, percentToFloor } from './roomSpace'

describe('percentToFloor', () => {
  it('puts the centre of the board at the origin', () => {
    expect(percentToFloor(50, 50)).toEqual([0, 0])
  })

  it('spreads the board across the full floor', () => {
    // 2 and 98 are the extremes the board itself can store, so they should
    // land near — not beyond — the floor edges.
    const [minX, minZ] = percentToFloor(2, 2)
    const [maxX, maxZ] = percentToFloor(98, 98)

    expect(minX).toBeCloseTo(-0.48 * ROOM_SIZE)
    expect(minZ).toBeCloseTo(-0.48 * ROOM_SIZE)
    expect(maxX).toBeCloseTo(0.48 * ROOM_SIZE)
    expect(maxZ).toBeCloseTo(0.48 * ROOM_SIZE)
  })
})

describe('floorToPercent', () => {
  it('round-trips a placement back to where it started', () => {
    // The property that matters: a word placed in 3D, reloaded, and drawn
    // again must not drift across the floor each time.
    for (const [x, y] of [
      [50, 50],
      [2, 98],
      [25, 75],
      [98, 2],
    ]) {
      const [fx, fz] = percentToFloor(x, y)
      expect(floorToPercent(fx, fz)).toEqual({ x_percent: x, y_percent: y })
    }
  })

  it('clamps a click past the floor edge into the storable range', () => {
    expect(floorToPercent(-999, 999)).toEqual({ x_percent: 2, y_percent: 98 })
  })
})

describe('clampPercent', () => {
  it('matches the 2D board, so the two views can store the same positions', () => {
    expect(clampPercent(0)).toBe(2)
    expect(clampPercent(100)).toBe(98)
    expect(clampPercent(50)).toBe(50)
  })

  it('turns a NaN into the centre rather than propagating it', () => {
    // A NaN reaching the scene puts a marker nowhere at all, and nothing on
    // screen explains where the word went.
    expect(clampPercent(Number.NaN)).toBe(50)
  })
})

describe('isWebglAvailable', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('reports false when a context cannot be created', () => {
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)
    expect(isWebglAvailable()).toBe(false)
  })

  it('reports false rather than throwing when the browser blocks the probe', () => {
    // Some privacy modes throw from getContext instead of returning null.
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(() => {
      throw new Error('blocked')
    })
    expect(isWebglAvailable()).toBe(false)
  })

  it('reports true when a context is returned', () => {
    // jsdom defines no WebGLRenderingContext, which the check reads as part
    // of deciding support — so a browser that has it has to be simulated.
    vi.stubGlobal('WebGLRenderingContext', function WebGLRenderingContext() {})
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({} as RenderingContext)

    expect(isWebglAvailable()).toBe(true)

    vi.unstubAllGlobals()
  })
})
