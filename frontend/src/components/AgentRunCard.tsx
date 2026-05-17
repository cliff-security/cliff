import type { AgentRun } from '@/api/client'
import Markdown from './Markdown'

const agentLabels: Record<string, string> = {
  finding_enricher: 'Finding Enricher',
  owner_resolver: 'Owner Resolver',
  exposure_analyzer: 'Exposure Analyzer',
  evidence_collector: 'Evidence Collector',
  remediation_planner: 'Remediation Planner',
  remediation_executor: 'Remediation Executor',
  validation_checker: 'Validation Checker',
}

export default function AgentRunCard({ run }: { run: AgentRun }) {
  const label = agentLabels[run.agent_type] ?? run.agent_type

  if (run.status === 'queued' || run.status === 'running') {
    return (
      <div className="max-w-3xl">
        <div className="bg-indigo-50/80 border border-indigo-100 rounded-xl p-4 flex items-center gap-4 shadow-sm">
          <div className="flex gap-1">
            <div className="w-1.5 h-1.5 rounded-full bg-primary/40 animate-bounce" style={{ animationDelay: '0ms' }} />
            <div className="w-1.5 h-1.5 rounded-full bg-primary/60 animate-bounce" style={{ animationDelay: '150ms' }} />
            <div className="w-1.5 h-1.5 rounded-full bg-primary/80 animate-bounce" style={{ animationDelay: '300ms' }} />
          </div>
          <p className="text-sm text-on-primary-fixed-variant font-medium">
            {label} is working...
          </p>
        </div>
      </div>
    )
  }

  if (run.status === 'rate_limited') {
    // EF-B17 — terminal state when the AI provider throttled us and the
    // executor's backoff retry budget was exhausted. Distinct from
    // ``failed`` because it's a transient/throttle condition, not a bug —
    // amber/warning tonal instead of red.
    return (
      <div className="max-w-3xl">
        <div className="bg-warning-container/40 rounded-xl p-4 flex flex-col gap-1.5">
          <p className="text-sm text-on-warning-container font-medium">
            {label} hit the AI provider rate limit
          </p>
          {run.last_error && (
            <p className="text-xs text-on-surface-variant">{run.last_error}</p>
          )}
        </div>
      </div>
    )
  }

  if (run.status === 'failed' || run.status === 'cancelled') {
    return (
      <div className="max-w-3xl">
        <div className="bg-error-container/20 border border-error/20 rounded-xl p-4 flex flex-col gap-1.5">
          <p className="text-sm text-error font-medium">
            {label} {run.status === 'failed' ? 'failed' : 'was cancelled'}
          </p>
          {run.last_error && (
            <p className="text-xs text-on-surface-variant">{run.last_error}</p>
          )}
        </div>
      </div>
    )
  }

  // Completed
  return (
    <div className="max-w-3xl self-start">
      <div className="bg-white rounded-2xl shadow-md overflow-hidden border border-surface-container/80">
        <div className="bg-primary/5 px-6 py-3 border-b border-surface-container/50 flex items-center justify-between">
          <h3 className="text-sm font-bold text-primary tracking-tight">
            {label} result
          </h3>
          <div className="flex items-center gap-3">
            {run.confidence != null && (
              <span className="text-[10px] font-bold text-primary-dim">
                {Math.round(run.confidence * 100)}% confidence
              </span>
            )}
            <span className="text-[10px] font-bold text-on-surface-variant uppercase bg-surface-container-high px-2 py-0.5 rounded">
              {run.id.slice(0, 8)}
            </span>
          </div>
        </div>
        <div className="p-6">
          {run.summary_markdown ? (
            <Markdown content={run.summary_markdown} />
          ) : (
            <p className="text-sm text-on-surface-variant">No summary available.</p>
          )}
        </div>
      </div>
    </div>
  )
}
