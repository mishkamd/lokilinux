import {
  LayoutDashboard, Server, Cpu, ClipboardList, ShieldAlert, Shield,
  FileText, Bot, Layers, ShieldCheck,
  GitCompare, FileSearch,
  Workflow, Siren, RadioTower, Activity, Network, GitMerge,
  BellDot, Puzzle, Users, Settings,
} from 'lucide-vue-next'

export interface NavLink {
  to: string
  label: string
  icon: unknown
  children?: NavLink[]
}

export interface NavSection {
  title: string
  links: NavLink[]
}

/**
 * The sidebar's information architecture, in one place so the layout and the
 * command palette can never disagree about what exists.
 *
 * Rules kept here (MIS-163): no label used twice, group headers are
 * expand-only (never a destination of their own), and every destination is
 * reachable from exactly one place.
 */
export function buildNavSections(opts: { isAdmin: boolean; ansibleEnabled: boolean }): NavSection[] {
  return [
    {
      // No section header: the dashboard is the app's front door, not a group.
      title: '',
      links: [
        { to: '/', label: 'Dashboard', icon: LayoutDashboard },
      ],
    },
    {
      title: 'Fleet',
      links: [
        { to: '/servers', label: 'Servers', icon: Server },
        { to: '/agents', label: 'Agents', icon: Cpu },
      ],
    },
    {
      title: 'Operate',
      links: [
        { to: '/jobs', label: 'Jobs', icon: ClipboardList },
        // Workflows and Runbooks are tabs of one area (pages/workflows.vue).
        { to: '/workflows', label: 'Workflows', icon: Workflow },
        // Enforcement policies (targets + triggers + actions), not compliance
        // policy sets — those live under Guard ▸ Compliance.
        { to: '/policies', label: 'Enforcement', icon: FileText },
        ...(opts.ansibleEnabled ? [{
          // Projects / Playbooks / Roles / Job Templates are tabs of one area
          // (pages/automation/ansible.vue).
          to: '/automation/ansible', label: 'Ansible', icon: Bot,
        }] : []),
      ],
    },
    {
      title: 'Guard',
      links: [
        { to: '/security',             label: 'Security Posture', icon: Shield },
        // Canonical vocabulary (CONCEPTS.md): Open Exposure = findings still
        // active on hosts right now; CVE Catalog = fleet-independent, all-time.
        // Open Exposure and the CVE Catalog are tabs of one area
        // (pages/vulnerabilities.vue).
        { to: '/vulnerabilities', label: 'Vulnerabilities', icon: ShieldAlert },
        {
          // Domain separation (Enterprise Compliance plan U2) is kept: Configuration
          // ("what should this host look like, and did it drift") and Compliance
          // ("does it satisfy a rule/standard") stay separate products — now two
          // groups under one Guard section instead of two side-by-side sections.
          to: '/compliance', label: 'Compliance', icon: ShieldCheck,
        },
        {
          to: '/compliance/baselines', label: 'Configuration', icon: Layers,
          children: [
            { to: '/compliance/baselines',      label: 'Baselines',      icon: FileText },
            { to: '/compliance/drift',          label: 'Drift',          icon: GitCompare },
            { to: '/compliance/file-integrity', label: 'File Integrity', icon: FileSearch },
          ],
        },
      ],
    },
    {
      title: 'Observe',
      links: [
        { to: '/incidents',   label: 'Incidents',   icon: Siren },
        {
          // One lifecycle (raw events -> signals -> alerts) behind one group.
          to: '/alerts', label: 'Detection', icon: RadioTower,
          children: [
            { to: '/alerts',  label: 'Alerts',  icon: BellDot },
            { to: '/signals', label: 'Signals', icon: RadioTower },
            { to: '/events',  label: 'Events',  icon: Activity },
          ],
        },
        { to: '/topology',    label: 'Topology',    icon: Network },
        { to: '/correlation', label: 'Correlation', icon: GitMerge },
      ],
    },
    ...(opts.isAdmin ? [{
      // Admin-gated: Plugins lives here too (it manages what the whole fleet can
      // run), so non-admins lose it from the nav — the route itself stays reachable.
      title: 'Admin',
      links: [
        { to: '/admin/settings', label: 'Settings',  icon: Settings },
        { to: '/admin/users',    label: 'Users',     icon: Users },
        { to: '/plugins',        label: 'Plugins',   icon: Puzzle },
        { to: '/admin/audit',    label: 'Audit Log', icon: ClipboardList },
      ],
    }] : []),
  ]
}

/**
 * Every destination the sidebar can take you to. Group headers are expand-only
 * in the UI, so they are not destinations — their children are. A group whose
 * children are all present therefore contributes each route exactly once.
 */
export function navDestinations(sections: NavSection[]): NavLink[] {
  return sections.flatMap((s) => s.links.flatMap((l) => (l.children?.length ? l.children : [l])))
}

export interface AreaTab {
  label: string
  to: string
}

/**
 * Tab definitions for the nested areas (MIS-166). Shared by the route shells
 * (pages/compliance.vue etc.) and the layout's page title, so the tab bar and
 * the document title can never disagree.
 */
export const COMPLIANCE_TABS: AreaTab[] = [
  { label: 'Overview', to: '/compliance' },
  { label: 'Standards', to: '/compliance/standards' },
  { label: 'Findings', to: '/compliance/findings' },
  { label: 'Policy Sets', to: '/compliance/policies' },
  { label: 'Rules', to: '/compliance/rules' },
  { label: 'Remediation', to: '/compliance/remediation' },
  { label: 'Exceptions', to: '/compliance/exceptions' },
  { label: 'Reports', to: '/compliance/reports' },
]

export const VULNERABILITY_TABS: AreaTab[] = [
  { label: 'Open Exposure', to: '/vulnerabilities' },
  { label: 'CVE Catalog', to: '/vulnerabilities/list' },
]

export const ANSIBLE_TABS: AreaTab[] = [
  { label: 'Projects', to: '/automation/ansible/projects' },
  { label: 'Playbooks', to: '/automation/ansible/playbooks' },
  { label: 'Roles', to: '/automation/ansible/roles' },
  { label: 'Job Templates', to: '/automation/ansible/templates' },
]

export const WORKFLOW_TABS: AreaTab[] = [
  { label: 'Workflows', to: '/workflows' },
  { label: 'Runbooks', to: '/workflows/runbooks' },
]

export const AREA_TABS: AreaTab[] = [
  ...COMPLIANCE_TABS,
  ...VULNERABILITY_TABS,
  ...ANSIBLE_TABS,
  ...WORKFLOW_TABS,
]
