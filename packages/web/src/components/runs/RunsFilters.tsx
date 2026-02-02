import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'
import { X, Search } from 'lucide-react'
import type { RunStatus, RunsFilters as RunsFiltersType } from '@/lib/interfaces'

const STATUS_OPTIONS: { value: RunStatus; label: string }[] = [
  { value: 'pending', label: 'Pending' },
  { value: 'queued', label: 'Queued' },
  { value: 'active', label: 'Active' },
  { value: 'complete', label: 'Complete' },
  { value: 'failed', label: 'Failed' },
  { value: 'cancelled', label: 'Cancelled' },
  { value: 'retrying', label: 'Retrying' },
]

interface RunsFiltersProps {
  filters: RunsFiltersType
  functions?: string[]
  onFiltersChange: (filters: RunsFiltersType) => void
}

export function RunsFilters({ filters, functions = [], onFiltersChange }: RunsFiltersProps) {
  const [searchId, setSearchId] = useState('')

  const handleStatusChange = (status: string) => {
    if (status === 'all') {
      const { status: _, ...rest } = filters
      onFiltersChange(rest)
    } else {
      onFiltersChange({ ...filters, status: status as RunStatus })
    }
  }

  const handleFunctionChange = (fn: string) => {
    if (fn === 'all') {
      const { function: _, ...rest } = filters
      onFiltersChange(rest)
    } else {
      onFiltersChange({ ...filters, function: fn })
    }
  }

  const handleSearch = () => {
    if (searchId.trim()) {
      // For searching by job ID, we would need to navigate to the detail page
      // or add a search by ID filter to the API
    }
  }

  const clearFilters = () => {
    setSearchId('')
    onFiltersChange({})
  }

  const activeFilterCount = [
    filters.status,
    filters.function,
    filters.worker_id,
    filters.after,
    filters.before,
  ].filter(Boolean).length

  return (
    <div className="flex flex-wrap items-center gap-3 pb-4">
      <Select
        value={typeof filters.status === 'string' ? filters.status : 'all'}
        onValueChange={handleStatusChange}
      >
        <SelectTrigger className="w-[140px]">
          <SelectValue placeholder="All statuses" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All statuses</SelectItem>
          {STATUS_OPTIONS.map((opt) => (
            <SelectItem key={opt.value} value={opt.value}>
              {opt.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {functions.length > 0 && (
        <Select
          value={filters.function || 'all'}
          onValueChange={handleFunctionChange}
        >
          <SelectTrigger className="w-[180px]">
            <SelectValue placeholder="All functions" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All functions</SelectItem>
            {functions.map((fn) => (
              <SelectItem key={fn} value={fn}>
                {fn}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}

      <div className="flex items-center gap-2">
        <Input
          placeholder="Search by ID..."
          value={searchId}
          onChange={(e) => setSearchId(e.target.value)}
          className="w-[180px]"
          onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
        />
        <Button variant="outline" size="icon" onClick={handleSearch}>
          <Search className="size-4" />
        </Button>
      </div>

      {activeFilterCount > 0 && (
        <div className="flex items-center gap-2">
          <Badge variant="secondary">
            {activeFilterCount} filter{activeFilterCount > 1 ? 's' : ''} active
          </Badge>
          <Button variant="ghost" size="sm" onClick={clearFilters}>
            <X className="mr-1 size-3" />
            Clear
          </Button>
        </div>
      )}
    </div>
  )
}
