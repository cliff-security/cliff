/**
 * App-wide context that lets any component open the AI provider modal.
 *
 * Eliminates prop-drilling — the modal is mounted once in AppLayout,
 * any agent button can call useOpenAIProvider().open() to surface it.
 */

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { AIProviderModal } from './AIProviderModal'

interface ContextValue {
  open: () => void
  close: () => void
  isOpen: boolean
}

const Ctx = createContext<ContextValue | null>(null)

export function AIProviderModalProvider({ children }: { children: ReactNode }) {
  const [isOpen, setIsOpen] = useState(false)

  const open = useCallback(() => setIsOpen(true), [])
  const close = useCallback(() => setIsOpen(false), [])

  const value = useMemo(() => ({ open, close, isOpen }), [open, close, isOpen])

  return (
    <Ctx.Provider value={value}>
      {children}
      <AIProviderModal open={isOpen} onClose={close} />
    </Ctx.Provider>
  )
}

export function useOpenAIProvider(): ContextValue {
  const ctx = useContext(Ctx)
  if (ctx === null) {
    // Tolerant fallback so non-wrapped tests don't blow up.
    return {
      open: () => {
        // no-op — provider missing
      },
      close: () => {
        // no-op
      },
      isOpen: false,
    }
  }
  return ctx
}
