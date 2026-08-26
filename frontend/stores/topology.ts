export interface TopologyNode {
  id: string
  tenant_id: string
  kind: string
  name: string
  agent_id: string | null
  created_at: string
}

export interface TopologyEdge {
  from_node: string
  to_node: string
  kind: string
}

export const useTopologyStore = defineStore('topology', () => {
  const api = useApi()

  const nodes = ref<TopologyNode[]>([])
  const edges = ref<TopologyEdge[]>([])
  const loading = ref(false)

  async function fetchGraph() {
    loading.value = true
    try {
      const data = await api.get<{ nodes: TopologyNode[]; edges: TopologyEdge[] }>('/topology')
      nodes.value = data.nodes
      edges.value = data.edges
    } catch {
      // swallow — global onResponseError already surfaces a toast
    } finally {
      loading.value = false
    }
  }

  async function createNode(payload: { kind: string; name: string }): Promise<TopologyNode> {
    const node = await api.post<TopologyNode>('/topology/nodes', payload)
    nodes.value.push(node)
    return node
  }

  async function addEdge(fromNode: string, toNode: string, kind = 'DEPENDS_ON') {
    await api.post('/topology/edges', { from_node: fromNode, to_node: toNode, kind })
    edges.value.push({ from_node: fromNode, to_node: toNode, kind })
  }

  async function removeEdge(fromNode: string, toNode: string) {
    await api.del(`/topology/edges?from_node=${fromNode}&to_node=${toNode}`)
    edges.value = edges.value.filter((e) => !(e.from_node === fromNode && e.to_node === toNode))
  }

  return { nodes, edges, loading, fetchGraph, createNode, addEdge, removeEdge }
})
