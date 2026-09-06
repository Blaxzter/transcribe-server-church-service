/**
 * Transcript and sidebar share one height. That is what keeps a long summary
 * from stretching the page: both columns end at the same line and scroll
 * internally. Kept as literal class strings so Tailwind can see them.
 */
export const DETAIL_GRID = "grid gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]";
export const TRANSCRIPT_PANE = "h-[min(70vh,44rem)] min-h-80";
export const SIDEBAR_PANE = "lg:h-[min(70vh,44rem)] lg:min-h-80";
