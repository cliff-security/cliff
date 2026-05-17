import { useCallback, useEffect, useRef, useState } from 'react';
import { api, type HealthStatus } from '../api/client';

interface ChatMessage {
  role: string;
  content: string;
}

export default function Spike() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [streaming, setStreaming] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  // Check health on mount
  useEffect(() => {
    api.health().then(setHealth).catch(console.error);
  }, []);

  // Auto-scroll
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streaming]);

  // Connect to SSE when session exists
  useEffect(() => {
    if (!sessionId) return;

    const es = api.streamEvents(sessionId);
    eventSourceRef.current = es;

    // Handle "text" events — streaming assistant content
    es.addEventListener('text', (event) => {
      // OpenCode sends the full text so far in each update, not a delta
      setStreaming(event.data);
      setSending(true);
    });

    // Handle "error" events
    es.addEventListener('error', (event: Event) => {
      try {
        const data = JSON.parse((event as MessageEvent).data);
        const errorMsg = data.message || 'Unknown error';
        setStreaming('');
        setMessages((msgs) => [
          ...msgs,
          { role: 'error', content: errorMsg },
        ]);
      } catch {
        // SSE connection error (not our custom error event)
      }
      setSending(false);
    });

    // Handle "done" events — finalize the assistant message
    es.addEventListener('done', () => {
      setStreaming((prev) => {
        if (prev) {
          setMessages((msgs) => [...msgs, { role: 'assistant', content: prev }]);
        }
        return '';
      });
      setSending(false);
    });

    return () => {
      es.close();
      eventSourceRef.current = null;
    };
  }, [sessionId]);

  const createSession = useCallback(async () => {
    try {
      const session = await api.createSession();
      setSessionId(session.id);
      setMessages([]);
      setStreaming('');
    } catch (err) {
      console.error('Failed to create session:', err);
    }
  }, []);

  const sendMessage = useCallback(async () => {
    if (!sessionId || !input.trim() || sending) return;

    const content = input.trim();
    setInput('');
    setMessages((prev) => [...prev, { role: 'user', content }]);
    setSending(true);
    setStreaming('');

    try {
      await api.sendMessage(sessionId, content);
    } catch (err) {
      console.error('Failed to send:', err);
      setMessages((prev) => [
        ...prev,
        { role: 'error', content: `Failed to send message: ${err}` },
      ]);
      setSending(false);
    }
  }, [sessionId, input, sending]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  return (
    <div style={{ maxWidth: 800, margin: '0 auto', padding: 20, fontFamily: 'system-ui' }}>
      <h1>Cliff — Phase 1 Spike</h1>

      {/* Health status */}
      <div style={{ marginBottom: 16, fontSize: 14, color: '#666' }}>
        Status:{' '}
        {health ? (
          <span>
            Cliff: <b>{health.cliff}</b> | OpenCode: <b>{health.opencode}</b> (v
            {health.opencode_version})
            {health.model && (
              <> | Model: <b>{health.model}</b></>
            )}
          </span>
        ) : (
          'checking...'
        )}
      </div>

      {/* Session controls */}
      <div style={{ marginBottom: 16 }}>
        <button onClick={createSession} style={buttonStyle}>
          {sessionId ? 'New Session' : 'Start Session'}
        </button>
        {sessionId && (
          <span style={{ marginLeft: 12, fontSize: 13, color: '#888' }}>
            Session: {sessionId.slice(0, 8)}...
          </span>
        )}
      </div>

      {/* Messages */}
      <div
        style={{
          border: '1px solid #ddd',
          borderRadius: 8,
          padding: 16,
          height: 400,
          overflowY: 'auto',
          marginBottom: 16,
          background: '#fafafa',
        }}
      >
        {messages.length === 0 && !streaming && (
          <div style={{ color: '#aaa', textAlign: 'center', marginTop: 160 }}>
            {sessionId ? 'Send a message to start...' : 'Create a session to begin'}
          </div>
        )}
        {messages.map((msg, i) => (
          <div key={i} style={{ marginBottom: 12 }}>
            <div
              style={{
                fontSize: 12,
                fontWeight: 600,
                color:
                  msg.role === 'user'
                    ? '#2563eb'
                    : msg.role === 'error'
                      ? '#dc2626'
                      : '#16a34a',
              }}
            >
              {msg.role}
            </div>
            <div
              style={{
                whiteSpace: 'pre-wrap',
                fontSize: 14,
                lineHeight: 1.5,
                ...(msg.role === 'error'
                  ? { color: '#dc2626', background: '#fef2f2', padding: 8, borderRadius: 4 }
                  : {}),
              }}
            >
              {msg.content}
            </div>
          </div>
        ))}
        {streaming && (
          <div style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: '#16a34a' }}>assistant</div>
            <div style={{ whiteSpace: 'pre-wrap', fontSize: 14, lineHeight: 1.5 }}>
              {streaming}
              <span style={{ opacity: 0.4 }}>▊</span>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div style={{ display: 'flex', gap: 8 }}>
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={sessionId ? 'Type a message...' : 'Create a session first'}
          disabled={!sessionId || sending}
          rows={2}
          style={{
            flex: 1,
            padding: 10,
            borderRadius: 8,
            border: '1px solid #ddd',
            fontSize: 14,
            fontFamily: 'system-ui',
            resize: 'none',
          }}
        />
        <button
          onClick={sendMessage}
          disabled={!sessionId || !input.trim() || sending}
          style={buttonStyle}
        >
          {sending ? '...' : 'Send'}
        </button>
      </div>
    </div>
  );
}

const buttonStyle: React.CSSProperties = {
  padding: '8px 20px',
  borderRadius: 8,
  border: '1px solid #ddd',
  background: '#111',
  color: '#fff',
  fontSize: 14,
  cursor: 'pointer',
};
