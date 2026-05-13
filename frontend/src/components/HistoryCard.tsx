import { useNavigate } from 'react-router'
import type { Workspace } from '@/api/client'
import { useAgentRuns, useFinding } from '@/api/hooks'
import ActionButton from './ActionButton'
import ListCard from './ListCard'

const stateStyles: Record<string, { label: string; classes: string }> = {
  open: { label: 'Open', classes: 'text-primary bg-primary/10 border border-primary/20' },
  waiting: { label: 'Waiting', classes: 'text-secondary bg-secondary/10 border border-secondary/20' },
  ready_to_close: { label: 'Ready to close', classes: 'text-tertiary bg-tertiary/10 border border-tertiary/20' },
  closed: { label: 'Closed', classes: 'text-green-700 bg-green-100 border border-green-200' },
  reopened: { label: 'Reopened', classes: 'text-primary bg-primary/10 border border-primary/20' },
}

const severityColors: Record<string, string> = {
  critical: 'text-error/70',
  high: 'text-error/60',
  medium: 'text-on-surface-variant',
  low: 'text-outline-variant',
}

const agentLabels: Record<string, string> = {
  finding_enricher: 'Enricher',
  owner_resolver: 'Owner',
  exposure_analyzer: 'Exposure',
  remediation_planner: 'Planner',
  validation_checker: 'Validator',
}

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime()
  const hours = Math.floor(diff / 3_600_000)
  if (hours < 1) return 'Just now'
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return days === 1 ? 'Yesterday' : `${days}d ago`
}

interface HistoryCardProps {
  workspace: Workspace
  onExport: () => void
}

export default function HistoryCard({ workspace, onExport }: HistoryCardProps) {
  const navigate = useNavigate()
  const { data: finding } = useFinding(workspace.finding_id)
  const { data: agentRuns } = useAgentRuns(workspace.id)

  const state = stateStyles[workspace.state] ?? stateStyles.open
  const completedRuns = (agentRuns ?? []).filter((r) => r.status === 'completed')
  const agentTypes = [...new Set(completedRuns.map((r) => r.agent_type))]
  const severityColor = severityColors[(finding?.raw_severity ?? 'medium').toLowerCase()] ?? severityColors.medium

  return (
    <ListCard>
      <div className="flex-1 min-w-0">
        <div className="flex flex-wrap items-center gap-2 mb-1">
          <span className={`text-[10px] font-bold uppercase tracking-wider px-2.5 py-1 rounded-md ${state.classes}`}>
            {state.label}
          </span>
          {finding?.raw_severity && (
            <span className={`text-[10px] font-medium uppercase tracking-wider ${severityColor}`}>
              {finding.raw_severity}
            </span>
          )}
          <span className="text-xs text-outline-variant">
            {timeAgo(workspace.updated_at)}
          </span>
        </div>
        <h3 className="text-base font-bold text-on-surface truncate">
          {finding?.title ?? 'Cliff is loading the finding…'}
        </h3>
        <div className="flex flex-wrap items-center gap-x-4 mt-1 text-xs text-on-surface-variant">
          {finding?.asset_label && (
            <span className="flex items-center gap-1">
              <span className="material-symbols-outlined text-xs">dns</span>
              {finding.asset_label}
            </span>
          )}
          {finding?.likely_owner && (
            <span className="flex items-center gap-1">
              <span className="material-symbols-outlined text-xs">groups</span>
              {finding.likely_owner}
            </span>
          )}
          {finding?.source_type && (
            <span className="flex items-center gap-1">
              <span className="material-symbols-outlined text-xs">hub</span>
              {finding.source_type}
            </span>
          )}
        </div>
        {agentTypes.length > 0 && (
          <div className="flex items-center gap-1 mt-2">
            {agentTypes.map((type) => (
              <span
                key={type}
                className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-primary-container/30 text-primary"
              >
                {agentLabels[type] ?? type}
              </span>
            ))}
          </div>
        )}
      </div>

      <div className="flex items-center gap-2 flex-shrink-0">
        <ActionButton label="Export" icon="download" variant="outline" onClick={onExport} />
        <ActionButton
          label="View"
          icon="visibility"
          onClick={() =>
            navigate(`/issues?open=${encodeURIComponent(workspace.finding_id)}`)
          }
        />
      </div>
    </ListCard>
  )
}
