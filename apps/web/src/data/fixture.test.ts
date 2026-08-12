import { describe, expect, it } from 'vitest'
import { createScenarioFixture, scenarioFixtureSchema } from './fixture'

describe('scenario fixture contract', () => {
  it('selects the requested number of eligible stops', () => {
    const fixture = createScenarioFixture({ shelterSlots: 8 })
    const selected = fixture.stops.filter((stop) => stop.selected)

    expect(selected).toHaveLength(8)
    expect(selected.every((stop) => stop.shelterCount === 0)).toBe(true)
  })

  it('satisfies the declared high-equity share', () => {
    const fixture = createScenarioFixture({ shelterSlots: 10, minimumEquityShare: 0.5 })
    const selected = fixture.stops.filter((stop) => stop.selected)
    const highEquity = selected.filter((stop) => stop.sviPercentile >= 0.75)

    expect(highEquity.length / selected.length).toBeGreaterThanOrEqual(0.5)
  })

  it('keeps the optimized proxy objective at or above the baseline', () => {
    const fixture = createScenarioFixture()

    expect(fixture.objectiveValue).toBeGreaterThanOrEqual(fixture.baselineValue)
  })

  it('validates every generated response through the runtime schema', () => {
    const fixture = createScenarioFixture({ shelterSlots: 12, equityWeight: 0.7 })

    expect(scenarioFixtureSchema.parse(fixture).runtimeMode).toBe('DEMO_FIXTURE')
  })
})
