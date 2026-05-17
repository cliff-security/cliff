import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { server } from '../../mocks/server'
import SummaryActionPanel from '../completion/SummaryActionPanel'

// Mock `exportCardAsPng` so tests don't depend on html-to-image / jsdom
// limitations. The real implementation is covered by imageExport.test.ts.
vi.mock('../../lib/imageExport', () => ({
  exportCardAsPng: vi.fn(async () => undefined),
  ExportError: class ExportError extends Error {},
}))

import { exportCardAsPng } from '../../lib/imageExport'

const props = {
  completionId: 'c-123',
  summaryText:
    'I secured fast-markdown with Cliff — 12 vulns fixed, branch protection enabled, SECURITY.md added. cliff.dev',
  summaryMarkdown:
    '![Secured by Cliff](cliff-summary.png)\n<!-- Completed 2026-04-14 -->',
  filename: 'fast-markdown_cliff-summary_2026-04-14.png',
  cardProps: {
    repoName: 'fast-markdown',
    completedAt: '2026-04-14',
    vulnsFixed: 12,
    postureChecksPassing: 5,
    prsMerged: 3,
    grade: 'A' as const,
  },
}

// Capture every POST the panel makes to the share-action endpoint.
function shareActionSpy() {
  const hits: Array<{ url: string; body: unknown }> = []
  server.events.on('request:start', async ({ request }) => {
    if (request.url.includes('/api/completion/') && request.method === 'POST') {
      const clone = request.clone()
      let body: unknown = null
      try {
        body = await clone.json()
      } catch {
        body = null
      }
      hits.push({ url: request.url, body })
    }
  })
  return hits
}

describe('SummaryActionPanel', () => {
  let writeText: ReturnType<typeof vi.fn>

  beforeEach(() => {
    writeText = vi.fn(async () => undefined)
    // Jsdom ships a built-in navigator.clipboard; replacing the whole
    // object can silently fail when it's defined as a getter. Patching
    // `writeText` on whatever clipboard currently exists is robust.
    if (!('clipboard' in navigator)) {
      Object.defineProperty(navigator, 'clipboard', {
        configurable: true,
        value: {},
      })
    }
    Object.defineProperty(navigator.clipboard, 'writeText', {
      configurable: true,
      writable: true,
      value: writeText,
    })
  })

  afterEach(() => {
    vi.clearAllMocks()
    server.events.removeAllListeners()
  })

  it('renders three action tiles with headers, previews, and buttons', () => {
    render(<SummaryActionPanel {...props} />)
    expect(screen.getByText(/Download image/i)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /Copy text summary/i })).toBeInTheDocument()
    expect(screen.getByText(/Copy README markdown/i)).toBeInTheDocument()

    // Download preview shows filename + dimensions metadata.
    expect(
      screen.getByText(/fast-markdown_cliff-summary_2026-04-14\.png/),
    ).toBeInTheDocument()
    expect(screen.getByText(/1200×630/)).toBeInTheDocument()

    // Buttons per the spec.
    expect(screen.getByRole('button', { name: /Save \.png/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Copy to clipboard$/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Copy markdown$/i })).toBeInTheDocument()
  })

  it('Save .png calls exportCardAsPng with the filename and posts download share-action', async () => {
    const hits = shareActionSpy()
    const user = userEvent.setup()
    render(<SummaryActionPanel {...props} />)

    await user.click(screen.getByRole('button', { name: /Save \.png/i }))

    expect(exportCardAsPng).toHaveBeenCalledTimes(1)
    const [, filename] = (exportCardAsPng as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(filename).toBe('fast-markdown_cliff-summary_2026-04-14.png')

    await vi.waitFor(() => {
      expect(hits.length).toBe(1)
    })
    expect(hits[0].url).toMatch(/\/api\/completion\/c-123\/share-action$/)
    expect(hits[0].body).toEqual({ action: 'download' })
  })

  it('Copy text writes to clipboard and posts copy_text share-action', async () => {
    const hits = shareActionSpy()
    const user = userEvent.setup()
    render(<SummaryActionPanel {...props} />)

    await user.click(screen.getByRole('button', { name: /^Copy to clipboard$/i }))

    await vi.waitFor(() => {
      expect(writeText).toHaveBeenCalledWith(props.summaryText)
      expect(hits.length).toBe(1)
    })
    expect(hits[0].body).toEqual({ action: 'copy_text' })
  })

  it('Copy markdown writes to clipboard and posts copy_markdown share-action', async () => {
    const hits = shareActionSpy()
    const user = userEvent.setup()
    render(<SummaryActionPanel {...props} />)

    await user.click(screen.getByRole('button', { name: /^Copy markdown$/i }))

    await vi.waitFor(() => {
      expect(writeText).toHaveBeenCalledWith(props.summaryMarkdown)
      expect(hits.length).toBe(1)
    })
    expect(hits[0].body).toEqual({ action: 'copy_markdown' })
  })

  it('double-clicks collapse to a single share-action POST (in-flight guard)', async () => {
    const hits = shareActionSpy()
    const user = userEvent.setup()
    render(<SummaryActionPanel {...props} />)

    const btn = screen.getByRole('button', { name: /^Copy to clipboard$/i })
    // Rapid double-click: dispatch both events back-to-back without awaiting
    // the first handler's microtasks to drain. The in-flight Set MUST hold
    // the second click as a no-op until the first handler fully settles.
    btn.click()
    btn.click()

    // Let async handlers settle.
    await vi.waitFor(() => {
      expect(writeText).toHaveBeenCalled()
    })
    // Give any stray second POST a chance to arrive, then assert exactly one.
    await new Promise((r) => setTimeout(r, 20))
    expect(hits.length).toBe(1)
    // Suppress unused-arg lint for `user`.
    void user
  })

  it('fires the optional onAction callback after each action', async () => {
    const onAction = vi.fn()
    const user = userEvent.setup()
    render(<SummaryActionPanel {...props} onAction={onAction} />)

    await user.click(screen.getByRole('button', { name: /^Copy to clipboard$/i }))
    await vi.waitFor(() => expect(onAction).toHaveBeenCalledWith('copy_text'))
  })

  it('renders the locked-local footer message about no uploads / no tracking', () => {
    render(<SummaryActionPanel {...props} />)
    expect(
      screen.getByText(/generated on your machine/i),
    ).toBeInTheDocument()
  })
})
