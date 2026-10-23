// Shared Unovis donut tooltip. Every dashboard donut renders the same segment
// shape (name / count / share), so the template lives here instead of being
// copied into each widget.
//
// Unovis's Donut wraps each datum in a d3 pie-arc object before binding it
// to the DOM segment (`{ ...pieArc, data: originalDatum, ... }`), so the
// tooltip trigger receives that wrapper, not the segment itself.
export interface DonutSegment {
  name: string
  count: number
  pct: number
}

export function donutTooltipTemplate(arc: { data: DonutSegment }): string {
  const d = arc.data
  return `
    <div style="background:var(--popover);color:var(--popover-foreground);border:1px solid var(--border);border-radius:var(--radius-sm);padding:6px 8px;box-shadow:var(--shadow-overlay);font-size:0.75rem;">
      <span style="font-weight:600;">${d.name}</span>: ${d.count} (${d.pct}%)
    </div>
  `
}
