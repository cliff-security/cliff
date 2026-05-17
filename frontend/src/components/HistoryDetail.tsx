import { useEffect, useState } from 'react'
import { api, type Workspace } from '@/api/client'
import { useAgentRuns, useFinding, useSidebar } from '@/api/hooks'
import AgentRunCard from './AgentRunCard'
import Markdown from './Markdown'
import WorkspaceSidebar from './WorkspaceSidebar'

interface ChatMessage {
  role: string
  content: string
}

interface HistoryDetailProps {
  workspace: Workspace
}

export default function HistoryDetail({ workspace }: HistoryDetailProps) {
  const { data: finding } = useFinding(workspace.finding_id)
  const { data: sidebar } = useSidebar(workspace.id)
  const { data: agentRuns } = useAgentRuns(workspace.id)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [activeTab, setActiveTab] = useState<'chat' | 'agents' | 'context'>('chat')

  // Load chat messages from OpenCode session.
  useEffect(() => {
    const sessionId = workspace.current_focus
    if (!sessionId) return
    let cancelled = false

    api.getSession(sessionId).then((detail) => {
      if (cancelled) return
      const history = detail.messages
        .filter((m) => m.content.trim())
        .map((m) => ({ role: m.role, content: m.content }))
      setMessages(history)
    }).catch(() => {
      // Session may no longer exist.
    })

    return () => { cancelled = true }
  }, [workspace.current_focus])

  const completedRuns = (agentRuns ?? []).filter(
    (r) =>
      r.status === 'completed' ||
      r.status === 'failed' ||
      r.status === 'rate_limited',
  )

  const tabs = [
    { key: 'chat' as const, label: 'Chat replay', icon: 'chat', count: messages.length },
    { key: 'agents' as const, label: 'Agent runs', icon: 'smart_toy', count: completedRuns.length },
    { key: 'context' as const, label: 'Context', icon: 'info' },
  ]

  return (
    <div className="border-t border-surface-container/50 bg-surface-container-low/50">
      {/* Tab bar */}
      <div className="flex gap-1 px-5 pt-3">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
              activeTab === tab.key
                ? 'bg-primary-container/40 text-primary'
                : 'text-on-surface-variant hover:bg-surface-container'
            }`}
          >
            <span className="material-symbols-outlined text-sm">{tab.icon}</span>
            {tab.label}
            {tab.count != null && (
              <span className="text-[10px] bg-surface-container-high rounded-full px-1.5">
                {tab.count}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="p-5 max-h-[500px] overflow-y-auto">
        {activeTab === 'chat' && (
          <ChatReplay messages={messages} />
        )}
        {activeTab === 'agents' && (
          <div className="space-y-4">
            {completedRuns.length === 0 ? (
              <p className="text-xs text-on-surface-variant italic">No agent runs recorded.</p>
            ) : (
              completedRuns.map((run) => (
                <AgentRunCard key={run.id} run={run} />
              ))
            )}
          </div>
        )}
        {activeTab === 'context' && (
          <div className="flex gap-6">
            <div className="flex-1">
              {finding?.description && (
                <div className="mb-4">
                  <h4 className="text-xs font-bold uppercase tracking-widest text-on-surface-variant mb-2">
                    Finding description
                  </h4>
                  <p className="text-sm text-on-surface-variant leading-relaxed">
                    {finding.description}
                  </p>
                </div>
              )}
              {finding?.why_this_matters && (
                <div>
                  <h4 className="text-xs font-bold uppercase tracking-widest text-on-surface-variant mb-2">
                    Why this matters
                  </h4>
                  <p className="text-sm text-on-surface leading-relaxed">
                    {finding.why_this_matters}
                  </p>
                </div>
              )}
            </div>
            <div className="w-72 hidden lg:block">
              <WorkspaceSidebar sidebar={sidebar} />
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function ChatReplay({ messages }: { messages: ChatMessage[] }) {
  if (messages.length === 0) {
    return (
      <p className="text-xs text-on-surface-variant italic">
        No chat messages recorded for this workspace.
      </p>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      {messages.map((msg, i) => (
        <div
          key={i}
          className={`max-w-2xl ${msg.role === 'user' ? 'self-end' : 'self-start'}`}
        >
          {msg.role === 'user' ? (
            <div className="bg-primary text-white rounded-2xl rounded-br-md px-4 py-2.5 shadow-sm">
              <p className="text-xs leading-relaxed whitespace-pre-wrap">{msg.content}</p>
            </div>
          ) : (
            <div className="bg-white rounded-2xl rounded-bl-md px-4 py-3 shadow-sm border border-surface-container/80">
              <div className="flex items-center gap-1.5 mb-1.5">
                <span className="material-symbols-outlined text-primary text-xs">auto_awesome</span>
                <span className="text-[10px] font-bold text-on-surface-variant uppercase tracking-wider">
                  Cliff
                </span>
              </div>
              <div className="text-xs">
                <Markdown content={msg.content} />
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
