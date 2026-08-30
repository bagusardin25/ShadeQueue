import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { scenarioFixture } from '../data/fixture'
import { CorridorMap } from './CorridorMap'

describe('CorridorMap', () => {
  it('shows selected shelter details on the map surface', () => {
    const recommended = scenarioFixture.stops.find((stop) => stop.selected)
    expect(recommended).toBeTruthy()

    render(
      <CorridorMap
        stops={scenarioFixture.stops}
        selectedStopId={recommended!.stopId}
        onSelect={() => undefined}
      />,
    )

    const details = screen.getByLabelText('Selected stop details')
    expect(details).toHaveTextContent(recommended!.name)
    expect(details).toHaveTextContent(recommended!.stopId)
    expect(details).toHaveTextContent('Recommended new shelter')
    expect(details).toHaveTextContent('Hot hours')
    expect(details).toHaveTextContent(recommended!.exceedanceHours.toFixed(1))
  })
})
