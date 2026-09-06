import { de } from "@/i18n/de";
import { formatCount, formatDuration } from "@/lib/utils";
import { SearchInput } from "@/components/ui/search-input";
import { Select } from "@/components/ui/select";
import {
  JOB_FILTERS,
  JOB_SORTS,
  type JobFilter,
  type JobSort,
} from "@/components/jobs/jobFilters";

interface JobsToolbarProps {
  query: string;
  onQueryChange: (value: string) => void;
  filter: JobFilter;
  onFilterChange: (value: JobFilter) => void;
  sort: JobSort;
  onSortChange: (value: JobSort) => void;
  /** Rows after filtering, and the untouched total behind them. */
  shown: number;
  total: number;
  duration: number;
}

export function JobsToolbar({
  query,
  onQueryChange,
  filter,
  onFilterChange,
  sort,
  onSortChange,
  shown,
  total,
  duration,
}: JobsToolbarProps) {
  const filtered = shown !== total;

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <SearchInput
          value={query}
          onValueChange={onQueryChange}
          placeholder={de.jobs.search}
          aria-label={de.common.search}
          wrapperClassName="min-w-56 flex-1"
        />
        <Select
          value={filter}
          onChange={(event) => onFilterChange(event.target.value as JobFilter)}
          aria-label={de.common.filter}
        >
          {JOB_FILTERS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </Select>
        <Select
          value={sort}
          onChange={(event) => onSortChange(event.target.value as JobSort)}
          aria-label={de.common.sort}
        >
          {JOB_SORTS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </Select>
      </div>

      <p className="text-xs text-muted-foreground" aria-live="polite">
        {filtered
          ? `${shown} ${de.common.of} ${formatCount(total, de.units.recordingOne, de.units.recordingMany)}`
          : formatCount(total, de.units.recordingOne, de.units.recordingMany)}
        {duration > 0 && (
          <span> · {de.jobs.totalDuration} {formatDuration(duration)}</span>
        )}
      </p>
    </div>
  );
}
