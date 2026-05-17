/**
 * SummaryActionPanel — the three share-action tiles (IMPL-0002 Milestone H4).
 *
 * The frozen Session 0 contract fixes the four required props. `cardProps`
 * is an additive Session F prop: when present, the panel renders a native
 * 1200×630 `ShareableSummaryCard` inside a CSS-scaled wrapper (transform on
 * the wrapper, NEVER on the card — html-to-image captures the card's ref
 * and any ancestor transform would break the render). When omitted, the
 * preview column collapses and Save .png becomes a no-op.
 */
import { useRef, type ReactNode } from 'react'
import ShareableSummaryCard, {
  type ShareableSummaryCardProps,
} from './ShareableSummaryCard'
import { exportCardAsPng } from '../../lib/imageExport'
import { useShareAction, type ShareAction } from './useShareAction'

export interface SummaryActionPanelProps {
  completionId: string
  summaryText: string
  summaryMarkdown: string
  filename: string
  onAction?: (action: ShareAction) => void
  /** Additive Session F prop — card data for the inline preview + PNG export. */
  cardProps?: ShareableSummaryCardProps
}

const PREVIEW_SCALE = 0.4
const PREVIEW_WIDTH = 1200 * PREVIEW_SCALE
const PREVIEW_HEIGHT = 630 * PREVIEW_SCALE

interface TileProps {
  icon: string
  title: string
  description: string
  preview: ReactNode
  buttonLabel: string
  buttonClassName: string
  onClick: () => void
}

function Tile({ icon, title, description, preview, buttonLabel, buttonClassName, onClick }: TileProps) {
  return (
    <div className="bg-surface-container-lowest rounded-xl shadow-sm p-5">
      <div className="flex items-start gap-3 mb-3">
        <span className="material-symbols-outlined text-primary mt-0.5">{icon}</span>
        <div className="flex-1 min-w-0">
          <h4 className="font-headline text-sm font-bold text-on-surface">{title}</h4>
          <p className="text-xs text-on-surface-variant mt-0.5">{description}</p>
        </div>
      </div>
      {preview}
      <button type="button" onClick={onClick} className={buttonClassName}>
        {buttonLabel}
      </button>
    </div>
  )
}

const PRIMARY_BUTTON =
  'w-full px-4 py-2.5 rounded-lg bg-primary text-white font-bold text-sm hover:bg-primary-dim transition-colors active:scale-95 shadow-sm'
const SECONDARY_BUTTON =
  'w-full px-4 py-2.5 rounded-lg bg-surface-container-low text-on-surface font-semibold text-sm hover:bg-surface-container'

export default function SummaryActionPanel({
  completionId,
  summaryText,
  summaryMarkdown,
  filename,
  onAction,
  cardProps,
}: SummaryActionPanelProps) {
  const cardRef = useRef<HTMLDivElement>(null)
  const record = useShareAction(completionId)

  function handleDownload() {
    void record('download', async () => {
      try {
        if (cardRef.current) {
          await exportCardAsPng(cardRef.current, filename)
        }
      } catch (err) {
        console.warn('PNG export failed:', err)
      }
      onAction?.('download')
    })
  }

  function handleCopy(action: 'copy_text' | 'copy_markdown', payload: string) {
    void record(action, async () => {
      try {
        await navigator.clipboard.writeText(payload)
      } catch (err) {
        console.warn('clipboard write failed:', err)
      }
      onAction?.(action)
    })
  }

  return (
    <div data-testid="SummaryActionPanel" className="mx-auto max-w-4xl" id="summary-panel">
      <div className="mb-6">
        <span className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">
          Your summary is ready
        </span>
        <h3 className="font-headline text-3xl font-extrabold tracking-tight text-on-surface mt-2">
          Share it, keep it, or ignore it
        </h3>
        <p className="text-on-surface-variant text-sm mt-1 max-w-xl">
          Generated locally in your browser. Nothing is uploaded. Nothing
          touches your repo unless you choose to paste the markdown yourself.
        </p>
      </div>

      <div className="grid md:grid-cols-[1.3fr_1fr] gap-6">
        {cardProps && (
          <div
            className="rounded-2xl shadow-sm overflow-hidden"
            style={{ width: `${PREVIEW_WIDTH}px`, height: `${PREVIEW_HEIGHT}px` }}
          >
            <div style={{ transform: `scale(${PREVIEW_SCALE})`, transformOrigin: 'top left' }}>
              <ShareableSummaryCard ref={cardRef} {...cardProps} />
            </div>
          </div>
        )}

        <div className="space-y-3">
          <Tile
            icon="download"
            title="Download image"
            description="Ready for social posts or your site."
            preview={
              <div className="bg-surface-container-low rounded-lg px-3 py-2.5 text-[11px] font-mono text-on-surface-variant leading-relaxed mb-3 flex items-center gap-2">
                <span className="material-symbols-outlined text-sm text-on-surface-variant">image</span>
                <span className="flex-1 min-w-0 truncate">{filename}</span>
                <span className="text-on-surface-variant/70">1200×630 · ~80 KB</span>
              </div>
            }
            buttonLabel="Save .png"
            buttonClassName={PRIMARY_BUTTON}
            onClick={handleDownload}
          />
          <Tile
            icon="content_copy"
            title="Copy text summary"
            description="Tweet-sized — drop it anywhere."
            preview={
              <pre className="bg-surface-container-low rounded-lg px-3 py-2.5 text-[11px] font-mono text-on-surface leading-relaxed mb-3 whitespace-pre-wrap">
                {summaryText}
              </pre>
            }
            buttonLabel="Copy to clipboard"
            buttonClassName={SECONDARY_BUTTON}
            onClick={() => handleCopy('copy_text', summaryText)}
          />
          <Tile
            icon="code"
            title="Copy README markdown"
            description="Paste it into your README yourself if you want."
            preview={
              <pre className="bg-surface-container-low rounded-lg px-3 py-2.5 text-[11px] font-mono text-on-surface leading-relaxed mb-3 overflow-x-auto">
                {summaryMarkdown}
              </pre>
            }
            buttonLabel="Copy markdown"
            buttonClassName={SECONDARY_BUTTON}
            onClick={() => handleCopy('copy_markdown', summaryMarkdown)}
          />
        </div>
      </div>

      <div className="mt-6 rounded-xl bg-surface-container-low px-5 py-4 flex items-start gap-3">
        <span className="material-symbols-outlined text-on-surface-variant mt-0.5">lock</span>
        <p className="text-sm text-on-surface-variant">
          This card is generated on your machine. No Cliff-hosted URL, no
          tracking, no account required. v1.2 will add an optional public
          badge with verification — not today.
        </p>
      </div>
    </div>
  )
}
