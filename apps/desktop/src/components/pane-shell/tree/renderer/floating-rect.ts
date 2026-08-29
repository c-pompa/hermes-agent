/**
 * Floating-pane geometry — pure, so the clamping/anchoring rules are testable
 * without a DOM.
 *
 * A floating pane is NOT a track in the layout tree: it never takes width from
 * a zone. It's a fixed-position card the tree renders above itself. Its whole
 * contract is "stay a sane rect inside the viewport", which is this module.
 */

/** Corner a floating pane spawns from (and re-anchors to on reset). */
export type FloatingAnchor = 'bottom-left' | 'bottom-right' | 'center' | 'top-left' | 'top-right'

export interface FloatingRect {
  x: number
  y: number
  width: number
  height: number
}

export interface FloatingViewport {
  width: number
  height: number
  /** Chrome reserved at the top (the 34px titlebar) — panes never cover it. */
  top: number
}

/** Keep this much of the card on screen when clamping, so it stays grabbable. */
const MIN_VISIBLE = 48

/** Gap between a spawned pane and the viewport edge it anchors to. */
export const FLOATING_MARGIN = 12

/** The one non-tiling placement — see renderer/floating-panes.tsx. */
export const FLOATING_PLACEMENT = 'floating'

export const clamp = (n: number, lo: number, hi: number): number => Math.min(Math.max(n, lo), hi)

/**
 * Clamp a rect into the viewport. Horizontal keeps `MIN_VISIBLE` px on screen
 * from either edge (a card can hang off the right, never vanish); vertical is
 * hard-bounded by the reserved chrome so the drag handle is always reachable.
 *
 * Both axes clamp `lo` before `hi`, so a card wider/taller than the viewport
 * pins to the top-left rather than inverting.
 */
export function clampFloatingRect(rect: FloatingRect, viewport: FloatingViewport): FloatingRect {
  const maxX = Math.max(MIN_VISIBLE - rect.width, viewport.width - MIN_VISIBLE)
  const maxY = Math.max(viewport.top, viewport.height - MIN_VISIBLE)

  return {
    ...rect,
    x: clamp(rect.x, Math.min(MIN_VISIBLE - rect.width, maxX), maxX),
    y: clamp(rect.y, viewport.top, maxY)
  }
}

/** Spawn position for an anchor — the corner, inset by `FLOATING_MARGIN`,
 *  or centered for the `'center'` anchor. */
export function anchoredRect(
  anchor: FloatingAnchor,
  size: { width: number; height: number },
  viewport: FloatingViewport
): FloatingRect {
  if (anchor === 'center') {
    return centeredRect(size, viewport)
  }

  const right = anchor === 'bottom-right' || anchor === 'top-right'
  const bottom = anchor === 'bottom-left' || anchor === 'bottom-right'

  const rect = {
    ...size,
    x: right ? viewport.width - size.width - FLOATING_MARGIN : FLOATING_MARGIN,
    y: bottom ? viewport.height - size.height - FLOATING_MARGIN : viewport.top + FLOATING_MARGIN
  }

  return clampFloatingRect(rect, viewport)
}

/** Center a rect in the usable viewport, then clamp so it stays grabbable. */
export function centeredRect(
  size: { width: number; height: number },
  viewport: FloatingViewport
): FloatingRect {
  return clampFloatingRect(
    {
      ...size,
      x: (viewport.width - size.width) / 2,
      y: viewport.top + (viewport.height - viewport.top - size.height) / 2
    },
    viewport
  )
}

/**
 * Re-clamp on viewport resize. A pane anchored to a right/bottom edge TRACKS
 * that edge (shrinking the window keeps it in the corner) instead of being
 * dragged inward only when it would fall off — matching how the pet and every
 * OS HUD behave.
 */
export function reflowRect(
  rect: FloatingRect,
  anchor: FloatingAnchor,
  previous: FloatingViewport,
  next: FloatingViewport
): FloatingRect {
  if (anchor === 'center') {
    return centeredRect({ width: rect.width, height: rect.height }, next)
  }

  const right = anchor === 'bottom-right' || anchor === 'top-right'
  const bottom = anchor === 'bottom-left' || anchor === 'bottom-right'

  return clampFloatingRect(
    {
      ...rect,
      x: right ? rect.x + (next.width - previous.width) : rect.x,
      y: bottom ? rect.y + (next.height - previous.height) : rect.y
    },
    next
  )
}

/** Parse an authored CSS length (`'216px'`, `216`, `'92vw'`, `'85vh'`)
 *  into px for geometry. Viewport-relative units need the current viewport.
 *  Falls back for unknown expressions (e.g. `calc(...)` / `min(...)`). */
export function floatingPx(
  value: number | string | undefined,
  fallback: number,
  viewport?: FloatingViewport
): number {
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : fallback
  }

  const str = value ?? ''
  const numeric = Number.parseFloat(str)

  if (!Number.isFinite(numeric)) {
    return fallback
  }

  if (viewport && str.endsWith('vw')) {
    return (viewport.width * numeric) / 100
  }

  if (viewport && str.endsWith('vh')) {
    return (viewport.height * numeric) / 100
  }

  return numeric
}
