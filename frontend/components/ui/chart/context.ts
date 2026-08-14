import type { InjectionKey } from 'vue'
import type { ChartConfig } from './types'

export const ChartConfigKey: InjectionKey<ChartConfig> = Symbol('chart-config')
