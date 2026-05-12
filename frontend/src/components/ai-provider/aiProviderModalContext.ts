/**
 * Internal context object for the AI provider modal.
 *
 * Lives in its own non-component module so `react-refresh/only-export-components`
 * stays happy on the provider component and the hook.
 */

import { createContext, useContext } from 'react'

export interface AIProviderModalContextValue {
  open: () => void
  close: () => void
  isOpen: boolean
}

export const AIProviderModalContext =
  createContext<AIProviderModalContextValue | null>(null)

export function useOpenAIProvider(): AIProviderModalContextValue {
  const ctx = useContext(AIProviderModalContext)
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
