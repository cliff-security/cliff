/**
 * WorkspaceRedirect — PRD-0006 Phase 2 / IMPL-0007 §F9.
 *
 * The standalone /workspace/:id page is gone. Existing bookmarks and any
 * lingering links resolve through this 301-equivalent redirect: look up the
 * workspace, then send the user to /issues?open=<finding_id> so the side
 * panel opens for the correct issue. If the workspace lookup fails (deleted,
 * never existed) we fall through to the bare /issues page.
 */
import { useEffect } from 'react'
import { Navigate, useNavigate, useParams } from 'react-router'
import { useWorkspace } from '@/api/hooks'

export default function WorkspaceRedirect() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { data: workspace, isLoading, isError } = useWorkspace(id)

  useEffect(() => {
    if (workspace?.finding_id) {
      navigate(`/issues?open=${encodeURIComponent(workspace.finding_id)}`, {
        replace: true,
      })
    }
  }, [navigate, workspace])

  if (!id) {
    return <Navigate to="/issues" replace />
  }

  if (isError) {
    return <Navigate to="/issues" replace />
  }

  if (isLoading || !workspace) {
    // Brief spinner while we look up the finding_id — keeps the redirect from
    // flashing /issues twice.
    return (
      <div className="flex justify-center py-24">
        <div className="w-8 h-8 border-3 border-primary/30 border-t-primary rounded-full animate-spin" />
      </div>
    )
  }

  return null
}
