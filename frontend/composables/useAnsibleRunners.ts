/**
 * Runner servers for an Ansible run.
 *
 * The agent reports the job types it can run natively in its heartbeat
 * (ANSIBLE_PLAYBOOK only when ansible-core is on the host). The control
 * plane mirrors the same rule (utils/capability_rbac.agent_can_run_job_type):
 * an agent that reports NO capabilities predates the field — its abilities
 * are unknown, not empty — so it is not blocked.
 */

const ANSIBLE_JOB_TYPE = 'ANSIBLE_PLAYBOOK'

/**
 * Whether an agent that reports `capabilities` can run Ansible.
 *
 * Mirrors the backend rule (utils/capability_rbac.agent_can_run_job_type):
 * an agent that reports NO capabilities predates the field — its abilities
 * are unknown, not empty — so it is not blocked.
 */
export function canRunAnsible(capabilities: string[] | null | undefined): boolean {
  const reported = capabilities ?? []
  if (!reported.length) return true
  return reported.includes(ANSIBLE_JOB_TYPE)
}

export interface RunnerOption {
  label: string
  value: string
  /** True when the agent says it cannot run this job type. */
  blocked: boolean
}

export function useAnsibleRunners() {
  const serversStore = useServersStore()
  const raw = ref<Array<{ label: string; value: string; capabilities: string[] }>>([])

  async function load() {
    if (!raw.value.length) {
      const fetched = await serversStore.fetchAgentsForSelect()
      raw.value = fetched.map((o) => ({
        label: o.label,
        value: o.value,
        capabilities: o.capabilities ?? [],
      }))
    }
  }

  const options = computed<RunnerOption[]>(() =>
    raw.value
      .map((o) => {
        const blocked = !canRunAnsible(o.capabilities)
        return {
          label: blocked ? `${o.label} · no ansible-core` : o.label,
          value: o.value,
          blocked,
        }
      })
      // Compatible runners first — the operator should not have to scroll
      // past the hosts that cannot run the playbook.
      .sort((a, b) => Number(a.blocked) - Number(b.blocked)),
  )

  const blockedIds = computed(() => new Set(options.value.filter((o) => o.blocked).map((o) => o.value)))

  const compatibleCount = computed(() => options.value.length - blockedIds.value.size)

  /** The blocked runners among the current selection, for the error message. */
  function blockedSelection(selected: string[]): string[] {
    return selected.filter((id) => blockedIds.value.has(id))
  }

  return { load, options, blockedIds, compatibleCount, blockedSelection }
}
