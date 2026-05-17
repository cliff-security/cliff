import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// We mock html-to-image at the module level so that the dynamic import
// inside `imageExport.ts` resolves to our controlled stub. Returning a
// small Blob is enough for the jsdom Object URL flow.
vi.mock('html-to-image', () => ({
  toBlob: vi.fn(async () => new Blob(['png bytes'], { type: 'image/png' })),
}))

import * as htmlToImage from 'html-to-image'
import { exportCardAsPng } from '../imageExport'

describe('exportCardAsPng', () => {
  const origCreateObjectURL = URL.createObjectURL
  const origRevokeObjectURL = URL.revokeObjectURL

  beforeEach(() => {
    // Provide jsdom with predictable URL.createObjectURL / revoke spies.
    URL.createObjectURL = vi.fn(() => 'blob:mock-url')
    URL.revokeObjectURL = vi.fn()
  })

  afterEach(() => {
    URL.createObjectURL = origCreateObjectURL
    URL.revokeObjectURL = origRevokeObjectURL
    vi.clearAllMocks()
  })

  it('calls html-to-image.toBlob with the spec options', async () => {
    const node = document.createElement('div')
    document.body.appendChild(node)

    await exportCardAsPng(node, 'cliff-summary.png')

    expect(htmlToImage.toBlob).toHaveBeenCalledTimes(1)
    const [passedNode, options] = (htmlToImage.toBlob as ReturnType<typeof vi.fn>)
      .mock.calls[0]
    expect(passedNode).toBe(node)
    expect(options).toMatchObject({
      width: 1200,
      height: 630,
      pixelRatio: 2,
      cacheBust: true,
    })
  })

  it('awaits document.fonts.ready before rasterizing (Safari fix)', async () => {
    const order: string[] = []
    const originalFonts = document.fonts
    // Replace `document.fonts` with a promise whose resolution we can observe.
    Object.defineProperty(document, 'fonts', {
      configurable: true,
      value: {
        ready: Promise.resolve().then(() => {
          order.push('fonts.ready')
        }),
      },
    })
    ;(htmlToImage.toBlob as ReturnType<typeof vi.fn>).mockImplementationOnce(
      async () => {
        order.push('toBlob')
        return new Blob(['png'], { type: 'image/png' })
      },
    )

    const node = document.createElement('div')
    document.body.appendChild(node)
    await exportCardAsPng(node, 'x.png')

    expect(order).toEqual(['fonts.ready', 'toBlob'])

    Object.defineProperty(document, 'fonts', {
      configurable: true,
      value: originalFonts,
    })
  })

  it('throws a typed error when the source node is null (lets callers show a fallback)', async () => {
    await expect(exportCardAsPng(null, 'x.png')).rejects.toThrow(/null/i)
  })

  it('triggers a browser download by appending, clicking, and removing an anchor', async () => {
    const node = document.createElement('div')
    document.body.appendChild(node)

    const appendSpy = vi.spyOn(document.body, 'appendChild')
    // We also verify the anchor is removed from the DOM afterwards.

    await exportCardAsPng(node, 'fast-markdown_cliff-summary_2026-04-14.png')

    // One append for the anchor (the test node itself was appended before
    // the spy was installed, so it doesn't count).
    expect(appendSpy).toHaveBeenCalledTimes(1)
    const anchor = appendSpy.mock.calls[0][0] as HTMLAnchorElement
    expect(anchor.tagName).toBe('A')
    expect(anchor.download).toBe('fast-markdown_cliff-summary_2026-04-14.png')
    expect(anchor.href).toMatch(/^blob:/)
    // After the function resolves the anchor should not be in the DOM.
    expect(document.body.contains(anchor)).toBe(false)
  })
})
