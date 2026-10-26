// @vitest-environment jsdom
import { windowOpacityFor } from '@hermes/shared/translucency'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// Linux: the preload bridge reports neither translucency nor glass (see
// `hermes:translucency:support` in electron/main.ts), so Settings hides the
// row and there is no lever to turn a fade back off. The X11 window manager
// still honours `setOpacity` (_NET_WM_WINDOW_OPACITY), so whatever this store
// resolves and mirrors to main is what the user sees.
//
// The bug: the defaults table has no Linux row, so an untouched (or migrated
// empty) book resolved to the macOS default — clear at 29% — and the renderer
// mirrored that to main on every boot, which persisted it to translucency.json
// and faded the window to ~94% with no visible setting to undo it.

const KEY = 'hermes.desktop.translucency.v2'
const desktopWindow = window as unknown as { hermesDesktop?: Partial<Window['hermesDesktop']> }

async function loadOnLinux(persisted?: unknown) {
  Object.defineProperty(navigator, 'platform', { configurable: true, value: 'Linux x86_64' })
  document.documentElement.dataset.hermesDesktopHost = 'electron'

  if (persisted !== undefined) {
    localStorage.setItem(KEY, JSON.stringify(persisted))
  }

  const setTranslucency = vi.fn()

  desktopWindow.hermesDesktop = { glassSupported: false, translucencySupported: false, setTranslucency }
  vi.resetModules()

  const store = await import('@/store/translucency')

  return { setTranslucency, store }
}

describe('translucency on an unsupported platform (Linux)', () => {
  beforeEach(() => {
    localStorage.clear()
    document.documentElement.removeAttribute('data-hermes-clear')
  })

  afterEach(() => {
    Reflect.deleteProperty(desktopWindow, 'hermesDesktop')
    vi.restoreAllMocks()
    vi.resetModules()
  })

  it('runs its assertions for real in this environment', async () => {
    const { store } = await loadOnLinux()

    expect(store.TRANSLUCENCY_SUPPORTED).toBe(false)
    expect(store.GLASS_SUPPORTED).toBe(false)
  })

  it('resolves an untouched profile to fully opaque, not the macOS 29% default', async () => {
    const { setTranslucency, store } = await loadOnLinux()

    expect(store.$translucency.get()).toMatchObject({ intensity: 0, fade: 0, mode: 'clear' })
    expect(windowOpacityFor(store.$translucency.get())).toBe(1)
    // What main persists to translucency.json and applies natively.
    expect(setTranslucency).toHaveBeenCalled()
    expect(setTranslucency.mock.lastCall?.[0]).toMatchObject({ intensity: 0, fade: 0 })
    expect(document.documentElement.hasAttribute('data-hermes-clear')).toBe(false)
  })

  it('resolves the exact migrated book from the user report to opaque', async () => {
    // Read verbatim from the migrated profile's localStorage.
    const { setTranslucency, store } = await loadOnLinux({ mode: 'clear', base: {}, light: {}, dark: {} })

    for (const appearance of ['dark', 'light'] as const) {
      store.setAppearance(appearance)
      expect(store.$translucency.get()).toMatchObject({ intensity: 0, fade: 0 })
      expect(windowOpacityFor(setTranslucency.mock.lastCall?.[0])).toBe(1)
    }
  })

  it('ignores a tuned value carried over from a supported machine without destroying it', async () => {
    const carried = { mode: 'glass', base: { intensity: 60, fade: 40 }, light: {}, dark: { intensity: 80 } }
    const { setTranslucency, store } = await loadOnLinux(carried)

    expect(store.$translucency.get()).toMatchObject({ intensity: 0, fade: 0, mode: 'clear' })
    expect(windowOpacityFor(setTranslucency.mock.lastCall?.[0])).toBe(1)
    expect(document.documentElement.hasAttribute('data-hermes-clear')).toBe(false)
    // The book itself is the user's data: gating is applied at resolution, so
    // the stored values survive (and would resolve again on a platform that
    // can honour them) rather than being silently rewritten.
    expect(store.$translucencyBook.get().base).toEqual({ intensity: 60, fade: 40 })
    expect(store.$translucencyBook.get().dark).toEqual({ intensity: 80 })
  })

  it('stays opaque when something still writes a value to the book', async () => {
    const { setTranslucency, store } = await loadOnLinux()

    store.setTranslucency(70)

    expect(store.$translucency.get().intensity).toBe(0)
    expect(windowOpacityFor(setTranslucency.mock.lastCall?.[0])).toBe(1)
  })
})
