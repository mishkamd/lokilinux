export interface ArchAvail { amd64: boolean; arm64: boolean }

export interface PackagesResponse {
  version: string
  platform_url: string
  rpm: { amd64: string; arm64: string }
  deb: { amd64: string; arm64: string }
  tar_gz: { amd64: string; arm64: string }
  available?: { rpm: ArchAvail; deb: ArchAvail; 'tar.gz': ArchAvail }
}

export interface PkgLink {
  label: string
  os: 'rpm' | 'deb' | 'tar.gz'
  arch: 'amd64' | 'arm64'
  external: string
  available: boolean
  filename: string
}

export interface PackageCard {
  type: string
  description: string
  links: PkgLink[]
}

export function buildPackageCards(p: PackagesResponse | null): PackageCard[] {
  if (!p) return []
  const v = p.version
  const mk = (os: PkgLink['os'], arch: PkgLink['arch'], external: string, filename: string): PkgLink => ({
    label: arch === 'amd64' ? 'amd64 (x86_64)' : 'arm64 (aarch64)',
    os, arch, external, filename,
    available: p.available?.[os]?.[arch] ?? false,
  })
  return [
    { type: 'RPM', description: 'RHEL · CentOS · Fedora · Rocky', links: [
      mk('rpm', 'amd64', p.rpm.amd64, `lokilinux-agent-${v}-1.x86_64.rpm`),
      mk('rpm', 'arm64', p.rpm.arm64, `lokilinux-agent-${v}-1.aarch64.rpm`),
    ] },
    { type: 'DEB', description: 'Debian · Ubuntu · Mint', links: [
      mk('deb', 'amd64', p.deb.amd64, `lokilinux-agent_${v}_amd64.deb`),
      mk('deb', 'arm64', p.deb.arm64, `lokilinux-agent_${v}_arm64.deb`),
    ] },
    { type: 'TAR.GZ', description: 'Any Linux distribution', links: [
      mk('tar.gz', 'amd64', p.tar_gz.amd64, `lokilinux-agent_${v}_linux_amd64.tar.gz`),
      mk('tar.gz', 'arm64', p.tar_gz.arm64, `lokilinux-agent_${v}_linux_arm64.tar.gz`),
    ] },
  ]
}
