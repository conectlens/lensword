/**
 * Mapping stored word placements onto a 3D room floor (issue #339).
 *
 * **Why no new coordinate shape.** A placement is stored as
 * `x_percent`/`y_percent` — two numbers describing a position on a square,
 * which is exactly what a position on a square floor is. Reading them as
 * floor coordinates means the backend contract, the persisted rows and the
 * 2D board all keep working untouched, and every placement made before this
 * feature existed appears in the 3D room with no migration to write or to
 * get wrong. A third axis would be a real change (words floating at
 * different heights); nothing in the issue asks for one, and inventing it
 * would require a schema change to store something no interaction sets.
 *
 * The conversions live here, apart from the scene, because they are the
 * part that can be tested without a GPU.
 */

/** Floor extent in world units; the room is `ROOM_SIZE` square. */
export const ROOM_SIZE = 10

/**
 * The same 2–98% clamp the 2D board applies when dropping a word.
 *
 * Kept identical on purpose: a word placed in the 3D room and one placed on
 * the 2D board have to be storable at the same positions, or switching view
 * would quietly move things.
 */
export function clampPercent(value: number): number {
  if (Number.isNaN(value)) return 50
  return Math.max(2, Math.min(98, value))
}

/** Stored percentages → floor `[x, z]`, centred on the origin. */
export function percentToFloor(xPercent: number, yPercent: number): [number, number] {
  return [
    (clampPercent(xPercent) / 100 - 0.5) * ROOM_SIZE,
    (clampPercent(yPercent) / 100 - 0.5) * ROOM_SIZE,
  ]
}

/**
 * Floor `[x, z]` → stored percentages, clamped to the board's range.
 *
 * Rounded to two decimals — far finer than any board is drawn — because
 * these numbers are persisted and read back. Unrounded, converting to the
 * floor and home again returns 2.0000000000000018 for 2, and every
 * place-reload-place cycle writes another slightly different value for a
 * word nobody moved.
 */
export function floorToPercent(x: number, z: number): { x_percent: number; y_percent: number } {
  const round = (value: number) => Math.round(value * 100) / 100
  return {
    x_percent: round(clampPercent((x / ROOM_SIZE + 0.5) * 100)),
    y_percent: round(clampPercent((z / ROOM_SIZE + 0.5) * 100)),
  }
}

/**
 * Whether this browser can actually draw a 3D scene.
 *
 * Checked before mounting rather than caught afterwards: a failed WebGL
 * context leaves a blank canvas with no error anyone sees, and "the room is
 * empty" is indistinguishable from "you have not placed anything yet".
 */
export function isWebglAvailable(): boolean {
  try {
    const canvas = document.createElement('canvas')
    return Boolean(
      window.WebGLRenderingContext &&
        (canvas.getContext('webgl') || canvas.getContext('experimental-webgl')),
    )
  } catch {
    // Some privacy modes throw rather than returning null.
    return false
  }
}
