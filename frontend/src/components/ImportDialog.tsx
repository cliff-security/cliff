import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, type ProviderInfo } from '@/api/client'
import { useModelConfig, useProviders, useStartIngest } from '@/api/hooks'
import IngestProgress from '@/components/IngestProgress'

const MAX_FILE_SIZE = 10 * 1024 * 1024 // 10MB

type Tab = 'upload' | 'paste'

interface ImportDialogProps {
  onComplete: () => void
  onClose: () => void
}

function guessSource(name: string): string {
  const lower = name.toLowerCase().replace(/\.json$/, '')
  for (const scanner of ['snyk', 'wiz', 'trivy', 'semgrep', 'checkov', 'prisma', 'sonarqube', 'grype', 'dependabot']) {
    if (lower.includes(scanner)) return scanner
  }
  return ''
}

export default function ImportDialog({ onComplete, onClose }: ImportDialogProps) {
  // Shared state (across tabs)
  const [tab, setTab] = useState<Tab>('upload')
  const [source, setSource] = useState('')
  const [modelOverride, setModelOverride] = useState('')
  const [jobId, setJobId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Upload tab state
  const [parsedData, setParsedData] = useState<Record<string, unknown>[] | null>(null)
  const [fileName, setFileName] = useState<string | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Paste tab state
  const [rawJson, setRawJson] = useState('')
  const [estimate, setEstimate] = useState<{
    total_items: number
    total_chunks: number
    estimated_tokens: number | null
  } | null>(null)
  const [estimating, setEstimating] = useState(false)

  // Model selector state
  const [showModelEdit, setShowModelEdit] = useState(false)
  const [modelSearch, setModelSearch] = useState('')
  const dropdownRef = useRef<HTMLDivElement>(null)

  const startIngest = useStartIngest()
  const { data: modelConfig } = useModelConfig()
  const { data: providers } = useProviders()

  const isRunning = jobId !== null
  const displayModel = modelOverride.trim() || modelConfig?.model_full_id || 'default'

  // Model search results
  const providerList = useMemo(() => (providers || []) as ProviderInfo[], [providers])
  const modelResults = useMemo(() => {
    const q = modelSearch.trim().toLowerCase()
    const results: { provider: ProviderInfo; matchingModels: [string, ProviderInfo['models'][string]][] }[] = []
    for (const provider of providerList) {
      const providerMatch = !q || provider.name.toLowerCase().includes(q) || provider.id.toLowerCase().includes(q)
      const matchingModels = Object.entries(provider.models).filter(
        ([id, model]) => !q || id.toLowerCase().includes(q) || (model.name && model.name.toLowerCase().includes(q))
      )
      if (providerMatch && !q) {
        results.push({ provider, matchingModels: Object.entries(provider.models) })
      } else if (matchingModels.length > 0) {
        results.push({ provider, matchingModels: providerMatch ? Object.entries(provider.models) : matchingModels })
      }
      if (results.length >= 8) break
    }
    return results
  }, [modelSearch, providerList])

  // Close model dropdown on click outside
  useEffect(() => {
    if (!showModelEdit) return
    const handleClick = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setShowModelEdit(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [showModelEdit])

  // ESC to close (input state only)
  useEffect(() => {
    if (isRunning) return
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [isRunning, onClose])

  // Debounced auto-estimate for paste tab. Stale estimate is cleared in the
  // change handlers (sync, in-event); the effect only runs the async fetch.
  useEffect(() => {
    if (tab !== 'paste' || !source.trim() || !rawJson.trim()) return
    let parsed: Record<string, unknown>[]
    try {
      const data = JSON.parse(rawJson)
      if (!Array.isArray(data) || data.length === 0) return
      parsed = data
    } catch {
      return
    }
    const timer = setTimeout(async () => {
      setEstimating(true)
      try {
        const res = await api.startIngest({ source, raw_data: parsed, dry_run: true })
        setEstimate({ total_items: res.total_items, total_chunks: res.total_chunks, estimated_tokens: res.estimated_tokens })
      } catch { /* best-effort */ }
      finally { setEstimating(false) }
    }, 800)
    return () => clearTimeout(timer)
  }, [tab, source, rawJson])

  // --- File upload helpers ---

  const processFile = useCallback((file: File) => {
    setError(null)
    setParsedData(null)
    setFileName(file.name)

    if (file.size > MAX_FILE_SIZE) {
      setError(`File too large (${(file.size / 1024 / 1024).toFixed(1)}MB). Maximum is 10MB.`)
      return
    }
    if (!file.name.endsWith('.json')) {
      setError('Only .json files are supported.')
      return
    }

    file.text().then((text) => {
      try {
        const data = JSON.parse(text)
        if (!Array.isArray(data) || data.length === 0) {
          setError('File must contain a non-empty JSON array of findings.')
          return
        }
        setParsedData(data)
        const detected = guessSource(file.name)
        if (detected && !source.trim()) setSource(detected)
      } catch {
        setError('Invalid JSON. The file must contain a valid JSON array.')
      }
    }).catch(() => {
      setError('Could not read file.')
    })
  }, [source])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    const file = e.dataTransfer.files[0]
    if (file) processFile(file)
  }, [processFile])

  const handleDragOver = useCallback((e: React.DragEvent) => { e.preventDefault(); setDragOver(true) }, [])
  const handleDragLeave = useCallback((e: React.DragEvent) => { e.preventDefault(); setDragOver(false) }, [])
  const handleFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) processFile(file)
  }, [processFile])

  // --- Submit ---

  const handleImport = useCallback(async () => {
    setError(null)

    const isReport = source.trim().toLowerCase() === 'report'

    let data: Record<string, unknown>[]
    if (tab === 'upload') {
      if (!parsedData) { setError('Select a file first.'); return }
      data = parsedData
    } else if (isReport) {
      // ADR-0051 / PRD-0008 — a vulnerability report is free-text prose, not
      // a scanner JSON array. Wrap the pasted text as a single ingest item so
      // the report-aware normalizer (source=report) can parse the claim.
      if (!rawJson.trim()) { setError('Paste the vulnerability report.'); return }
      data = [{ report: rawJson.trim() }]
    } else {
      try {
        const parsed = JSON.parse(rawJson)
        if (!Array.isArray(parsed) || parsed.length === 0) {
          setError('Input must be a non-empty JSON array.')
          return
        }
        data = parsed
      } catch {
        setError(
          'Invalid JSON. Paste a JSON array of findings from your scanner — ' +
            'or set the source to "report" to paste a vulnerability report.',
        )
        return
      }
    }

    if (!source.trim()) { setError('Enter a source name (e.g. snyk, wiz, report).'); return }

    try {
      const req = {
        source: source.trim(),
        raw_data: data,
        ...(modelOverride.trim() ? { model: modelOverride.trim() } : {}),
      }
      const res = await startIngest.mutateAsync(req)
      setJobId(res.job_id)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start import.')
    }
  }, [tab, parsedData, rawJson, source, modelOverride, startIngest])

  const canImport = source.trim() && (tab === 'upload' ? parsedData !== null : rawJson.trim()) && !startIngest.isPending

  const formatTokens = (n: number) => n >= 1000 ? `~${(n / 1000).toFixed(1)}k` : `~${n}`

  // --- Render ---

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-[2px]"
      onClick={!isRunning ? onClose : undefined}
    >
      <div
        className="bg-surface-container-lowest rounded-2xl shadow-xl w-full max-w-lg mx-4 overflow-hidden animate-in fade-in"
        onClick={(e) => e.stopPropagation()}
      >
        {/* When running, IngestProgress renders status strips here */}
        {isRunning && (
          <IngestProgress
            onComplete={onComplete}
            onClose={onClose}
            initialJobId={jobId!}
            initialSource={source}
            embedded
          />
        )}

        {/* Input state: header + tabs + shared fields + tab content + actions */}
        {!isRunning && (
          <div className="p-6">
            {/* Header */}
            <div className="flex items-center justify-between mb-5">
              <h3 className="font-headline text-base font-bold text-on-surface tracking-tight">
                Import findings
              </h3>
              <button
                onClick={onClose}
                className="p-1.5 text-on-surface-variant hover:text-on-surface rounded-md transition-colors"
              >
                <span className="material-symbols-outlined text-sm">close</span>
              </button>
            </div>

            {/* Tabs */}
            <div className="flex gap-1 bg-surface-container-low rounded-lg p-1 mb-5">
              <button
                onClick={() => { setTab('upload'); setEstimate(null) }}
                className={`flex-1 flex items-center justify-center gap-2 px-4 py-2 rounded-md text-sm font-semibold transition-colors ${
                  tab === 'upload'
                    ? 'bg-surface-container-lowest text-on-surface shadow-sm'
                    : 'text-on-surface-variant hover:text-on-surface'
                }`}
              >
                <span className="material-symbols-outlined text-sm">upload_file</span>
                Upload
              </button>
              <button
                onClick={() => { setTab('paste'); setEstimate(null) }}
                className={`flex-1 flex items-center justify-center gap-2 px-4 py-2 rounded-md text-sm font-semibold transition-colors ${
                  tab === 'paste'
                    ? 'bg-surface-container-lowest text-on-surface shadow-sm'
                    : 'text-on-surface-variant hover:text-on-surface'
                }`}
              >
                <span className="material-symbols-outlined text-sm">content_paste</span>
                Paste
              </button>
            </div>

            <div className="space-y-4">
              {/* Source field (shared) */}
              <div>
                <label className="text-xs font-semibold text-on-surface-variant block mb-1">
                  Source name
                </label>
                <input
                  type="text"
                  value={source}
                  onChange={(e) => { setSource(e.target.value); setEstimate(null) }}
                  placeholder="e.g. wiz, snyk, trivy"
                  className="w-full bg-surface-container-low rounded-lg px-3 py-2 text-sm text-on-surface outline-none focus:ring-2 focus:ring-primary/20 placeholder:text-outline-variant"
                />
              </div>

              {/* Model selector (shared) */}
              <div className="relative" ref={dropdownRef}>
                <div className="flex items-center justify-between bg-surface-container-low rounded-lg px-3 py-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="material-symbols-outlined text-sm text-on-surface-variant">smart_toy</span>
                    <span className="text-xs text-on-surface-variant">Model</span>
                    {showModelEdit ? (
                      <input
                        type="text"
                        value={modelSearch}
                        onChange={(e) => setModelSearch(e.target.value)}
                        placeholder="Type to filter models..."
                        autoFocus
                        onKeyDown={(e) => {
                          if (e.key === 'Escape') { e.stopPropagation(); setShowModelEdit(false); setModelSearch('') }
                        }}
                        className="flex-1 min-w-0 bg-surface-container-lowest rounded px-2 py-0.5 text-xs font-mono text-on-surface outline-none focus:ring-2 focus:ring-primary/20 placeholder:text-outline-variant"
                      />
                    ) : (
                      <span className="text-xs font-semibold text-on-surface font-mono truncate">
                        {displayModel}
                      </span>
                    )}
                  </div>
                  <button
                    onClick={() => { setShowModelEdit(!showModelEdit); setModelSearch('') }}
                    className="text-xs font-semibold text-primary hover:text-primary/80 transition-colors ml-2 flex-shrink-0"
                  >
                    {showModelEdit ? 'Done' : 'Change'}
                  </button>
                </div>

                {showModelEdit && modelResults.length > 0 && (
                  <div className="absolute left-0 right-0 top-full mt-1 z-10 bg-surface-container-lowest rounded-lg shadow-lg max-h-48 overflow-y-auto py-1">
                    {modelResults.map(({ provider, matchingModels }) => (
                      <div key={provider.id}>
                        <div className="px-3 pt-2 pb-1 text-[11px] font-semibold uppercase tracking-wider text-on-surface-variant">
                          {provider.name}
                        </div>
                        <div className="px-2 pb-1 flex flex-wrap gap-1">
                          {matchingModels.map(([modelId, model]) => {
                            const fullId = `${provider.id}/${modelId}`
                            const isActive = modelOverride === fullId || (!modelOverride && modelConfig?.model_full_id === fullId)
                            return (
                              <button
                                key={fullId}
                                onClick={() => {
                                  setModelOverride(fullId)
                                  setShowModelEdit(false)
                                  setModelSearch('')
                                }}
                                className={`px-2 py-1 rounded-md text-xs font-mono transition-colors ${
                                  isActive
                                    ? 'bg-primary text-on-primary shadow-sm'
                                    : 'bg-surface-container text-on-surface-variant hover:bg-primary/5'
                                }`}
                              >
                                {model.name || modelId}
                              </button>
                            )
                          })}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* --- UPLOAD TAB CONTENT --- */}
              {tab === 'upload' && (
                <>
                  <div
                    onDrop={handleDrop}
                    onDragOver={handleDragOver}
                    onDragLeave={handleDragLeave}
                    onClick={() => fileInputRef.current?.click()}
                    className={`rounded-xl py-10 px-6 flex flex-col items-center justify-center cursor-pointer transition-all ${
                      dragOver
                        ? 'bg-primary/5 ring-2 ring-primary/20'
                        : 'bg-surface-container-low hover:bg-surface-container'
                    }`}
                    style={{ border: '2px dashed', borderColor: dragOver ? 'var(--color-primary, #4d44e3)' : 'rgba(190,195,198,0.3)' }}
                  >
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept=".json"
                      className="hidden"
                      onChange={handleFileChange}
                    />
                    <div className="w-12 h-12 rounded-full bg-primary/10 flex items-center justify-center mb-3">
                      <span className="material-symbols-outlined text-2xl text-primary">upload_file</span>
                    </div>
                    <p className="text-sm font-semibold text-on-surface mb-1">
                      {fileName && parsedData ? fileName : 'Drop a JSON file here, or click to browse'}
                    </p>
                    <p className="text-xs text-on-surface-variant">
                      {fileName && parsedData
                        ? `${parsedData.length} finding${parsedData.length !== 1 ? 's' : ''} ready to import`
                        : 'Accepts .json up to 10MB'}
                    </p>
                  </div>
                </>
              )}

              {/* --- PASTE TAB CONTENT --- */}
              {tab === 'paste' && (
                <>
                  <div>
                    <label className="text-xs font-semibold text-on-surface-variant block mb-1">
                      Raw findings (JSON array)
                    </label>
                    <textarea
                      value={rawJson}
                      onChange={(e) => { setRawJson(e.target.value); setError(null); setEstimate(null) }}
                      placeholder={'[\n  { "id": "...", "title": "...", "severity": "..." },\n  ...\n]'}
                      className="w-full bg-surface-container-low rounded-xl px-3 py-2.5 text-sm font-mono text-on-surface outline-none focus:ring-2 focus:ring-primary/20 placeholder:text-outline-variant min-h-[180px] resize-y"
                    />
                  </div>

                  {/* Auto-estimate row */}
                  {(estimate || estimating) && !error && (
                    <div className="bg-surface-container-low rounded-lg px-4 py-2.5 flex items-center gap-2">
                      <span className={`material-symbols-outlined text-sm text-on-surface-variant ${estimating ? 'animate-spin' : ''}`}>
                        {estimating ? 'progress_activity' : 'token'}
                      </span>
                      <span className="text-xs text-on-surface-variant">
                        {estimating ? 'Estimating...' : (
                          estimate && (
                            <>
                              {estimate.total_items} findings in {estimate.total_chunks} chunk{estimate.total_chunks !== 1 ? 's' : ''}
                              {estimate.estimated_tokens != null && <>, {formatTokens(estimate.estimated_tokens)} tokens</>}
                            </>
                          )
                        )}
                      </span>
                    </div>
                  )}
                </>
              )}

              {/* Error (shared) */}
              {error && (
                <div className="bg-red-50 text-red-800 rounded-lg px-4 py-3 text-sm">
                  {error}
                </div>
              )}
            </div>

            {/* Footer */}
            <p className="text-xs text-on-surface-variant text-center mt-5">
              Tested with Snyk, Wiz, and generic JSON formats
            </p>

            {/* Actions */}
            <div className="flex justify-end gap-3 mt-5">
              <button
                onClick={onClose}
                className="px-4 py-2 text-sm font-semibold text-on-surface-variant hover:text-on-surface rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleImport}
                disabled={!canImport}
                className="px-5 py-2 bg-primary text-on-primary rounded-lg text-sm font-semibold hover:bg-primary-dim transition-colors disabled:opacity-40 active:scale-95 shadow-sm shadow-primary/10"
              >
                {startIngest.isPending ? 'Starting...' : 'Import'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
