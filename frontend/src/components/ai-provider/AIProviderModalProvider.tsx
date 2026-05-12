/**
 * App-wide context that lets any component open the AI provider modal.
 *
 * Eliminates prop-drilling — the modal is mounted once in AppLayout,
 * any agent button can call useOpenAIProvider().open() to surface it.
 *
 * The hook + context object live in ``aiProviderModalContext.ts`` so
 * Fast Refresh's `only-export-components` rule stays happy on this file.
 */

import { useCallback, useMemo, useState, type ReactNode } from 'react'
import { AIProviderModal } from './AIProviderModal'
import { AIProviderModalContext } from './aiProviderModalContext'

export function AIProviderModalProvider({ children }: { children: ReactNode }) {
  const [isOpen, setIsOpen] = useState(false)

  const open = useCallback(() => setIsOpen(true), [])
  const close = useCallback(() => setIsOpen(false), [])

  const value = useMemo(() => ({ open, close, isOpen }), [open, close, isOpen])

  return (
    <AIProviderModalContext.Provider value={value}>
      {children}
      <AIProviderModal open={isOpen} onClose={close} />
    </AIProviderModalContext.Provider>
  )
}
