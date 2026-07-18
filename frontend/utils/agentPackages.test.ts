import { describe, expect, it } from 'vitest'
import { buildPackageCards, type PackagesResponse } from './agentPackages'

const basePackages: PackagesResponse = {
  version: '0.2.0',
  platform_url: 'http://192.168.0.110:3000',
  rpm: { amd64: '', arm64: '' },
  deb: { amd64: '', arm64: '' },
  tar_gz: { amd64: '', arm64: '' },
}

describe('buildPackageCards', () => {
  it('returns an empty list when there is no packages response', () => {
    expect(buildPackageCards(null)).toEqual([])
  })

  it('marks a link available when the backend reports it as built', () => {
    const cards = buildPackageCards({
      ...basePackages,
      available: {
        rpm: { amd64: true, arm64: false },
        deb: { amd64: false, arm64: false },
        'tar.gz': { amd64: true, arm64: true },
      },
    })

    const rpm = cards.find(c => c.type === 'RPM')!
    expect(rpm.links.find(l => l.arch === 'amd64')!.available).toBe(true)
    expect(rpm.links.find(l => l.arch === 'arm64')!.available).toBe(false)
  })

  it('defaults availability to false when the backend omits the field', () => {
    const cards = buildPackageCards(basePackages)
    for (const card of cards) {
      for (const link of card.links) {
        expect(link.available).toBe(false)
      }
    }
  })

  it('builds rpm filenames with the nfpm release suffix', () => {
    const cards = buildPackageCards(basePackages)
    const rpm = cards.find(c => c.type === 'RPM')!
    expect(rpm.links.find(l => l.arch === 'amd64')!.filename).toBe('lokilinux-agent-0.2.0-1.x86_64.rpm')
    expect(rpm.links.find(l => l.arch === 'arm64')!.filename).toBe('lokilinux-agent-0.2.0-1.aarch64.rpm')
  })

  it('builds deb and tar.gz filenames without a release suffix', () => {
    const cards = buildPackageCards(basePackages)
    const deb = cards.find(c => c.type === 'DEB')!
    const tar = cards.find(c => c.type === 'TAR.GZ')!
    expect(deb.links.find(l => l.arch === 'amd64')!.filename).toBe('lokilinux-agent_0.2.0_amd64.deb')
    expect(tar.links.find(l => l.arch === 'amd64')!.filename).toBe('lokilinux-agent_0.2.0_linux_amd64.tar.gz')
  })
})
