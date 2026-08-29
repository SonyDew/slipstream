import {
  Check,
  RefreshCw,
  Search,
  Shield,
  Trash2,
  UserPlus,
  X,
} from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'

import { UserDetailDialog } from '@/components/admin/user-detail-dialog'
import { CreateUserDialog } from '@/components/admin/create-user-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/dialog'
import { ErrorCard } from '@/components/ui/feedback'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select } from '@/components/ui/select'
import {
  Pagination,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Table,
  TableEmptyRow,
  TableSkeletonRows,
  TableWrapper,
} from '@/components/ui/table'
import { useToast } from '@/components/ui/toast'
import { useAsyncData } from '@/hooks/use-async-data'
import { useDebounced } from '@/hooks/use-debounced'
import { ApiError, api } from '@/lib/api'
import { useAuth } from '@/lib/auth-context'
import type { AdminUser, Paginated } from '@/lib/types'
import { formatDateTime, formatNumber, formatRelative } from '@/lib/utils'

const PER_PAGE = 25

export function AdminUsersPage() {
  const toast = useToast()
  const { user: currentUser, mustChangePassword } = useAuth()

  const [query, setQuery] = useState('')
  const [role, setRole] = useState('')
  const [active, setActive] = useState('')
  const [page, setPage] = useState(1)

  const debouncedQuery = useDebounced(query)

  const [detailId, setDetailId] = useState<number | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<AdminUser | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [busyId, setBusyId] = useState<number | null>(null)

  const fetcher = useCallback(
    () =>
      api.admin.users({
        q: debouncedQuery.trim(),
        role,
        active,
        page,
        per_page: PER_PAGE,
      }),
    [debouncedQuery, role, active, page],
  )

  const { data, error, loading, reload } = useAsyncData<Paginated<AdminUser>>(fetcher)

  // Filter changes invalidate the current page number.
  useEffect(() => setPage(1), [debouncedQuery, role, active])

  const canMutate = !mustChangePassword

  const toggleActive = async (target: AdminUser) => {
    setBusyId(target.id)
    try {
      await api.admin.updateUser(target.id, { is_active: !target.is_active })
      toast.success(target.is_active ? 'Account disabled' : 'Account enabled', target.username)
      await reload(true)
    } catch (caught) {
      toast.error(
        'Could not update the account',
        caught instanceof ApiError ? caught.message : 'Please try again.',
      )
    } finally {
      setBusyId(null)
    }
  }

  const changeRole = async (target: AdminUser, nextRole: 'user' | 'admin') => {
    setBusyId(target.id)
    try {
      await api.admin.updateUser(target.id, { role: nextRole })
      toast.success(
        nextRole === 'admin' ? 'Granted administrator' : 'Removed administrator',
        target.username,
      )
      await reload(true)
    } catch (caught) {
      toast.error(
        'Could not change the role',
        caught instanceof ApiError ? caught.message : 'Please try again.',
      )
    } finally {
      setBusyId(null)
    }
  }

  const confirmDelete = async () => {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await api.admin.deleteUser(deleteTarget.id)
      toast.success('Account deleted', deleteTarget.username)
      setDeleteTarget(null)
      await reload(true)
    } catch (caught) {
      toast.error(
        'Could not delete the account',
        caught instanceof ApiError ? caught.message : 'Please try again.',
      )
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold tracking-tight">Users</h2>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => void reload()} loading={loading}>
            {!loading && <RefreshCw aria-hidden />}
            Refresh
          </Button>
          <Button
            variant="brand"
            size="sm"
            onClick={() => setCreateOpen(true)}
            disabled={!canMutate}
            title={canMutate ? undefined : 'Change your bootstrap password first'}
          >
            <UserPlus aria-hidden />
            New user
          </Button>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-[1fr_auto_auto]">
        <div className="space-y-1.5">
          <Label htmlFor="user-search" className="sr-only">
            Search users
          </Label>
          <div className="relative">
            <Search
              className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
              aria-hidden
            />
            <Input
              id="user-search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search username or email"
              className="pl-9"
              autoComplete="off"
            />
          </div>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="user-role" className="sr-only">
            Role
          </Label>
          <Select
            id="user-role"
            value={role}
            onChange={(event) => setRole(event.target.value)}
            className="sm:w-40"
          >
            <option value="">All roles</option>
            <option value="user">Users</option>
            <option value="admin">Administrators</option>
          </Select>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="user-active" className="sr-only">
            Status
          </Label>
          <Select
            id="user-active"
            value={active}
            onChange={(event) => setActive(event.target.value)}
            className="sm:w-40"
          >
            <option value="">Any status</option>
            <option value="true">Active</option>
            <option value="false">Disabled</option>
          </Select>
        </div>
      </div>

      {error && (
        <ErrorCard
          title="Could not load users"
          message={error.message}
          code={error.code}
          onRetry={() => void reload()}
          retrying={loading}
        />
      )}

      <TableWrapper>
        <Table>
          <THead>
            <TR>
              <TH>Account</TH>
              <TH>Role</TH>
              <TH>Status</TH>
              <TH className="text-right">Downloads</TH>
              <TH>Last seen</TH>
              <TH>Joined</TH>
              <TH className="text-right">Actions</TH>
            </TR>
          </THead>
          <TBody>
            {loading && !data ? (
              <TableSkeletonRows rows={8} columns={7} />
            ) : data && data.items.length > 0 ? (
              data.items.map((row) => {
                const isSelf = row.id === currentUser?.id
                const busy = busyId === row.id
                return (
                  <TR key={row.id}>
                    <TD>
                      <button
                        type="button"
                        onClick={() => setDetailId(row.id)}
                        className="rounded text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      >
                        <span className="block font-medium hover:underline">{row.username}</span>
                        <span className="block truncate text-xs text-muted-foreground">
                          {row.email || '—'}
                        </span>
                      </button>
                    </TD>
                    <TD>
                      {row.role === 'admin' ? (
                        <Badge variant="default">
                          <Shield aria-hidden />
                          Admin
                        </Badge>
                      ) : (
                        <Badge variant="muted">User</Badge>
                      )}
                    </TD>
                    <TD>
                      <span className="flex flex-col gap-1">
                        <Badge variant={row.is_active ? 'success' : 'muted'}>
                          {row.is_active ? 'Active' : 'Disabled'}
                        </Badge>
                        {row.must_change_password && (
                          <Badge variant="warning">Temp password</Badge>
                        )}
                      </span>
                    </TD>
                    <TD className="text-right tabular-nums">
                      {formatNumber(row.download_count ?? 0)}
                    </TD>
                    <TD className="whitespace-nowrap text-sm text-muted-foreground">
                      {row.last_login_at ? formatRelative(row.last_login_at) : 'Never'}
                    </TD>
                    <TD
                      className="whitespace-nowrap text-sm text-muted-foreground"
                      title={formatDateTime(row.created_at)}
                    >
                      {formatRelative(row.created_at)}
                    </TD>
                    <TD>
                      <div className="flex items-center justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => void toggleActive(row)}
                          disabled={!canMutate || busy || isSelf}
                          loading={busy}
                          title={
                            isSelf
                              ? 'You cannot disable your own account'
                              : row.is_active
                                ? 'Disable this account'
                                : 'Enable this account'
                          }
                        >
                          {!busy &&
                            (row.is_active ? <X aria-hidden /> : <Check aria-hidden />)}
                          {row.is_active ? 'Disable' : 'Enable'}
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() =>
                            void changeRole(row, row.role === 'admin' ? 'user' : 'admin')
                          }
                          disabled={!canMutate || busy || isSelf}
                          title={
                            isSelf
                              ? 'You cannot change your own role'
                              : row.role === 'admin'
                                ? 'Remove administrator'
                                : 'Make administrator'
                          }
                        >
                          {row.role === 'admin' ? 'Demote' : 'Promote'}
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          onClick={() => setDeleteTarget(row)}
                          disabled={!canMutate || busy || isSelf}
                          aria-label={`Delete ${row.username}`}
                          title={
                            isSelf ? 'You cannot delete your own account' : 'Delete this account'
                          }
                          className="text-muted-foreground hover:text-destructive"
                        >
                          <Trash2 aria-hidden />
                        </Button>
                      </div>
                    </TD>
                  </TR>
                )
              })
            ) : (
              <TableEmptyRow
                colSpan={7}
                message={
                  query || role || active
                    ? 'No accounts match those filters.'
                    : 'No accounts yet.'
                }
              />
            )}
          </TBody>
        </Table>
      </TableWrapper>

      {data && (
        <Pagination
          page={data.page}
          pages={data.pages}
          total={data.total}
          perPage={data.per_page}
          onPageChange={setPage}
        />
      )}

      <UserDetailDialog
        userId={detailId}
        onClose={() => setDetailId(null)}
        onChanged={() => void reload(true)}
        canMutate={canMutate}
      />

      <CreateUserDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={() => void reload(true)}
      />

      <ConfirmDialog
        open={deleteTarget !== null}
        onClose={() => setDeleteTarget(null)}
        onConfirm={() => void confirmDelete()}
        title={`Delete ${deleteTarget?.username ?? 'this account'}?`}
        description="The account, its sessions and its download history are removed permanently. Audit entries recording actions taken on this account are kept."
        confirmLabel="Delete account"
        loading={deleting}
      />
    </div>
  )
}
