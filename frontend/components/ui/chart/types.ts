export interface ChartSeriesConfig {
  label: string
  /** CSS color value — always a `var(--chart-N)` / `var(--destructive)` etc. token, never a hardcoded hex. */
  color: string
}

export type ChartConfig = Record<string, ChartSeriesConfig>

export interface ChartDataPoint {
  date: string
  value: number
}
