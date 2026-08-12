import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { scenarioFixture } from '../data/fixture'
import { StopsTable } from './StopsTable'

describe('StopsTable', () => {
  it('filters the accessible stop alternative and recovers from an empty result', () => {
    render(
      <StopsTable
        stops={scenarioFixture.stops}
        selectedStopId={scenarioFixture.stops[0]!.stopId}
        onSelect={() => undefined}
      />,
    )

    fireEvent.change(screen.getByRole('searchbox', { name: 'Search stops' }), {
      target: { value: 'not a real stop' },
    })

    expect(screen.getByText('No stops match this view')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }))
    expect(screen.getAllByText('Central Ave & Roosevelt St').length).toBeGreaterThan(0)
  })

  it('selects a stop through a named native button', () => {
    const onSelect = vi.fn()
    render(
      <StopsTable
        stops={scenarioFixture.stops}
        selectedStopId={scenarioFixture.stops[0]!.stopId}
        onSelect={onSelect}
      />,
    )

    fireEvent.click(screen.getAllByRole('button', { name: /Central Ave & Thomas Rd/ })[0]!)
    expect(onSelect).toHaveBeenCalledWith('SQ-103')
  })
})
