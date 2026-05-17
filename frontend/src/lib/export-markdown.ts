import type { Workspace } from '@/api/client'

interface ChatMessage {
  role: string
  content: string
}

/** Generate a markdown summary of a workspace for export. */
export function generateExportMarkdown(
  workspace: Workspace,
  finding: { title: string; raw_severity: string | null; asset_label: string | null; likely_owner: string | null; description: string | null } | undefined,
  messages: ChatMessage[],
  agentRuns: { agent_type: string; status: string; summary_markdown: string | null; confidence: number | null }[],
): string {
  const lines: string[] = []

  lines.push(`# Remediation: ${finding?.title ?? 'Unknown finding'}`)
  lines.push('')
  lines.push(`**Severity:** ${finding?.raw_severity ?? 'N/A'}`)
  lines.push(`**Asset:** ${finding?.asset_label ?? 'N/A'}`)
  lines.push(`**Owner:** ${finding?.likely_owner ?? 'N/A'}`)
  lines.push(`**Status:** ${workspace.state}`)
  lines.push(`**Created:** ${new Date(workspace.created_at).toLocaleDateString()}`)
  lines.push(`**Updated:** ${new Date(workspace.updated_at).toLocaleDateString()}`)
  lines.push('')

  if (finding?.description) {
    lines.push('## Finding description')
    lines.push('')
    lines.push(finding.description)
    lines.push('')
  }

  const completed = agentRuns.filter((r) => r.status === 'completed')
  if (completed.length > 0) {
    lines.push('## Agent results')
    lines.push('')
    for (const run of completed) {
      lines.push(`### ${run.agent_type.replace(/_/g, ' ')}`)
      if (run.confidence != null) {
        lines.push(`*Confidence: ${Math.round(run.confidence * 100)}%*`)
      }
      lines.push('')
      lines.push(run.summary_markdown ?? 'No summary.')
      lines.push('')
    }
  }

  if (messages.length > 0) {
    lines.push('## Chat transcript')
    lines.push('')
    for (const msg of messages) {
      const label = msg.role === 'user' ? '**User:**' : '**Cliff:**'
      lines.push(`${label} ${msg.content}`)
      lines.push('')
    }
  }

  return lines.join('\n')
}
