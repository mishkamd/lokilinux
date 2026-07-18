/**
 * WebSocket composable with exponential-backoff reconnect.
 * Client-side only — WebSocket does not exist on the server.
 *
 * Usage:
 *   const ws = useWebSocket()
 *   ws.on('agent:status', (data) => { ... })
 *   ws.send('job:log', { jobId: '...' })
 */

export type WsEventType = 'job:log' | 'agent:status' | 'alert' | 'metrics'
export type WsStatus = 'connecting' | 'connected' | 'disconnected' | 'error'
export type EventHandler<T = unknown> = (data: T) => void

export interface WebSocketInstance {
  on<T = unknown>(event: WsEventType, handler: EventHandler<T>): void
  off<T = unknown>(event: WsEventType, handler: EventHandler<T>): void
  send(event: WsEventType, data: unknown): void
  status: Ref<WsStatus>
  disconnect(): void
}

const INITIAL_DELAY_MS = 1_000
const MAX_DELAY_MS = 30_000

export function useWebSocket(path = '/ws'): WebSocketInstance {
  const config = useRuntimeConfig()
  const status = ref<WsStatus>('disconnected')
  // ponytail: Map<event, Set<handler>> — lightweight event emitter, no lib needed
  const handlers = new Map<WsEventType, Set<EventHandler>>()

  let ws: WebSocket | null = null
  let reconnectDelay = INITIAL_DELAY_MS
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null

  function connect(): void {
    if (!import.meta.client) return
    const wsBase = (config.public.apiBase as string).replace(/^http/, 'ws')
    ws = new WebSocket(`${wsBase}${path}`)
    status.value = 'connecting'

    ws.onopen = (): void => {
      status.value = 'connected'
      reconnectDelay = INITIAL_DELAY_MS
    }

    ws.onmessage = (event: MessageEvent<string>): void => {
      try {
        const { type, data } = JSON.parse(event.data) as { type: WsEventType; data: unknown }
        handlers.get(type)?.forEach((h) => h(data))
      } catch {
        // malformed frame — ignore
      }
    }

    ws.onclose = (): void => {
      status.value = 'disconnected'
      scheduleReconnect()
    }

    ws.onerror = (): void => {
      status.value = 'error'
      ws?.close()
    }
  }

  function scheduleReconnect(): void {
    reconnectTimer = setTimeout(() => {
      reconnectDelay = Math.min(reconnectDelay * 2, MAX_DELAY_MS)
      connect()
    }, reconnectDelay)
  }

  function disconnect(): void {
    if (reconnectTimer !== null) clearTimeout(reconnectTimer)
    ws?.close()
    ws = null
    status.value = 'disconnected'
  }

  onMounted(connect)
  onUnmounted(disconnect)

  return {
    on<T>(event: WsEventType, handler: EventHandler<T>): void {
      if (!handlers.has(event)) handlers.set(event, new Set())
      handlers.get(event)!.add(handler as EventHandler)
    },
    off<T>(event: WsEventType, handler: EventHandler<T>): void {
      handlers.get(event)?.delete(handler as EventHandler)
    },
    send(event: WsEventType, data: unknown): void {
      if (ws?.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: event, data }))
      }
    },
    status,
    disconnect,
  }
}
