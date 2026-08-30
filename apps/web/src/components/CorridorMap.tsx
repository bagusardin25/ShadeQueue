import { useEffect, useRef, useState } from 'react'
import * as maplibregl from 'maplibre-gl'
import type { GeoJSONSource, Map as MapLibreMap, MapLayerMouseEvent, StyleSpecification } from 'maplibre-gl'
import maplibreWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url'
import { Keyboard, Map as MapIcon, TriangleAlert } from 'lucide-react'
import type { Stop } from '../data/fixture'
import type { HeatmapLayer } from '../lib/api'
import { modeLabel } from '../lib/api'

maplibregl.setWorkerUrl(maplibreWorkerUrl)

interface CorridorMapProps {
  stops: Stop[]
  selectedStopId: string
  onSelect: (stopId: string) => void
  heatmap?: HeatmapLayer | null
  runtimeMode?: string
}

function stopCollection(stops: Stop[], selectedStopId: string) {
  return {
    type: 'FeatureCollection' as const,
    features: stops.map((stop) => ({
      type: 'Feature' as const,
      geometry: {
        type: 'Point' as const,
        coordinates: [stop.longitude, stop.latitude],
      },
      properties: {
        stopId: stop.stopId,
        selected: stop.stopId === selectedStopId ? 1 : 0,
        recommended: stop.selected ? 1 : 0,
        baseline: stop.baselineSelected ? 1 : 0,
        existingShelter: stop.shelterCount > 0 ? 1 : 0,
        heat: stop.exceedanceHours,
      },
    })),
  }
}

function heatCollection(stops: Stop[]) {
  return {
    type: 'FeatureCollection' as const,
    features: stops.map((stop) => ({
      type: 'Feature' as const,
      geometry: { type: 'Point' as const, coordinates: [stop.longitude, stop.latitude] },
      properties: { heat: stop.exceedanceHours },
    })),
  }
}

const streetCollection = {
  type: 'FeatureCollection' as const,
  features: [
    ...[33.448, 33.458, 33.465, 33.481, 33.488, 33.495, 33.506].map((latitude, index) => ({
      type: 'Feature' as const,
      geometry: {
        type: 'LineString' as const,
        coordinates: [
          [-112.092, latitude],
          [-112.064, latitude + (index % 2 === 0 ? 0.00025 : -0.0002)],
        ],
      },
      properties: {},
    })),
    ...[-112.088, -112.083, -112.078, -112.074, -112.069].map((longitude) => ({
      type: 'Feature' as const,
      geometry: {
        type: 'LineString' as const,
        coordinates: [
          [longitude, 33.442],
          [longitude + 0.0004, 33.514],
        ],
      },
      properties: {},
    })),
  ],
}

const corridorCollection = {
  type: 'FeatureCollection' as const,
  features: [
    {
      type: 'Feature' as const,
      geometry: {
        type: 'LineString' as const,
        coordinates: [
          [-112.0759, 33.444],
          [-112.074, 33.4587],
          [-112.0737, 33.4807],
          [-112.0731, 33.5015],
          [-112.0728, 33.511],
        ],
      },
      properties: {},
    },
    {
      type: 'Feature' as const,
      geometry: {
        type: 'LineString' as const,
        coordinates: [
          [-112.0832, 33.446],
          [-112.0827, 33.459],
          [-112.082, 33.4808],
          [-112.0814, 33.4952],
          [-112.081, 33.511],
        ],
      },
      properties: {},
    },
  ],
}

const emptyHeat: HeatmapLayer = { type: 'FeatureCollection', features: [] }

export function CorridorMap({ stops, selectedStopId, onSelect, heatmap, runtimeMode }: CorridorMapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<MapLibreMap | null>(null)
  const onSelectRef = useRef(onSelect)
  const initialSelectedStopId = useRef(selectedStopId)
  const [mapReady, setMapReady] = useState(false)
  const [mapFailed, setMapFailed] = useState(false)

  useEffect(() => {
    onSelectRef.current = onSelect
  }, [onSelect])

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return

    const style: StyleSpecification = {
      version: 8,
      sources: {
        streets: { type: 'geojson', data: streetCollection },
        corridor: { type: 'geojson', data: corridorCollection },
        heat: { type: 'geojson', data: heatCollection(stops) },
        heatPolygons: { type: 'geojson', data: heatmap ?? emptyHeat },
        stops: { type: 'geojson', data: stopCollection(stops, initialSelectedStopId.current) },
      },
      layers: [
        {
          id: 'canvas',
          type: 'background',
          paint: { 'background-color': '#ebe8dc' },
        },
        {
          id: 'streets-layer',
          type: 'line',
          source: 'streets',
          paint: { 'line-color': '#cbc7ba', 'line-width': 1.2, 'line-opacity': 0.75 },
        },
        {
          id: 'heat-polygons-fill',
          type: 'fill',
          source: 'heatPolygons',
          paint: {
            'fill-color': [
              'interpolate',
              ['linear'],
              ['coalesce', ['get', 'value'], 0],
              0,
              '#f5d887',
              6,
              '#eda052',
              10,
              '#d55b3d',
              14,
              '#862c29',
            ],
            'fill-opacity': 0.38,
          },
        },
        {
          id: 'heat-polygons-line',
          type: 'line',
          source: 'heatPolygons',
          paint: { 'line-color': '#9d2f20', 'line-width': 0.6, 'line-opacity': 0.45 },
        },
        {
          id: 'heat-layer',
          type: 'heatmap',
          source: 'heat',
          paint: {
            'heatmap-weight': ['interpolate', ['linear'], ['get', 'heat'], 5, 0.15, 13, 1],
            'heatmap-intensity': 0.72,
            'heatmap-radius': ['interpolate', ['linear'], ['zoom'], 11, 28, 14, 62],
            'heatmap-opacity': 0.62,
            'heatmap-color': [
              'interpolate',
              ['linear'],
              ['heatmap-density'],
              0,
              'rgba(255,255,255,0)',
              0.22,
              '#f5d887',
              0.48,
              '#eda052',
              0.72,
              '#d55b3d',
              1,
              '#862c29',
            ],
          },
        },
        {
          id: 'corridor-halo',
          type: 'line',
          source: 'corridor',
          paint: { 'line-color': '#fffdf7', 'line-width': 8, 'line-opacity': 0.9 },
        },
        {
          id: 'corridor-layer',
          type: 'line',
          source: 'corridor',
          paint: { 'line-color': '#1c3934', 'line-width': 3, 'line-dasharray': [1.2, 0.7] },
        },
        {
          id: 'stops-layer',
          type: 'circle',
          source: 'stops',
          paint: {
            'circle-radius': ['case', ['==', ['get', 'selected'], 1], 9, ['==', ['get', 'recommended'], 1], 6.5, 5],
            'circle-color': [
              'case',
              ['==', ['get', 'selected'], 1],
              '#0e6159',
              ['==', ['get', 'existingShelter'], 1],
              '#909991',
              ['==', ['get', 'recommended'], 1],
              '#fffdf7',
              '#f2c151',
            ],
            'circle-stroke-color': ['case', ['==', ['get', 'selected'], 1], '#fffdf7', '#142925'],
            'circle-stroke-width': ['case', ['==', ['get', 'selected'], 1], 3, 1.75],
          },
        },
      ],
    }

    try {
      const map = new maplibregl.Map({
        container: containerRef.current,
        style,
        center: [-112.078, 33.478],
        zoom: 12.15,
        attributionControl: false,
        cooperativeGestures: true,
      })

      map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')
      map.on('load', () => setMapReady(true))
      map.on('click', 'stops-layer', (event: MapLayerMouseEvent) => {
        const stopId = event.features?.[0]?.properties.stopId
        if (typeof stopId === 'string') onSelectRef.current(stopId)
      })
      map.on('mouseenter', 'stops-layer', () => {
        map.getCanvas().style.cursor = 'pointer'
      })
      map.on('mouseleave', 'stops-layer', () => {
        map.getCanvas().style.cursor = ''
      })
      map.getCanvas().addEventListener('webglcontextlost', () => setMapFailed(true), { once: true })
      mapRef.current = map
    } catch (error) {
      console.error('MapLibre initialization failed', error)
      queueMicrotask(() => setMapFailed(true))
    }

    return () => {
      mapRef.current?.remove()
      mapRef.current = null
    }
  }, [stops])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapReady) return
    const source = map.getSource('stops') as GeoJSONSource | undefined
    source?.setData(stopCollection(stops, selectedStopId))
    const heatSource = map.getSource('heatPolygons') as GeoJSONSource | undefined
    heatSource?.setData(heatmap ?? emptyHeat)
    const pointHeat = map.getSource('heat') as GeoJSONSource | undefined
    pointHeat?.setData(heatCollection(stops))
    if (map.getLayer('heat-layer')) {
      map.setLayoutProperty('heat-layer', 'visibility', heatmap?.features.length ? 'none' : 'visible')
    }
    const selected = stops.find((stop) => stop.stopId === selectedStopId)
    if (!selected) return
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    map.easeTo({
      center: [selected.longitude, selected.latitude],
      zoom: Math.max(map.getZoom(), 12.8),
      duration: reduceMotion ? 0 : 320,
    })
  }, [mapReady, selectedStopId, stops, heatmap])

  return (
    <section className="relative min-h-[31rem] overflow-hidden border border-line bg-[#ebe8dc]" aria-labelledby="map-title">
      <div className="pointer-events-none absolute inset-x-0 top-0 z-10 flex flex-wrap items-start justify-between gap-3 p-4">
        <div className="pointer-events-auto max-w-[18rem] border border-line bg-panel/95 p-3 shadow-[4px_4px_0_rgba(20,41,37,0.12)]">
          <p className="flex items-center gap-2 text-xs font-bold uppercase tracking-[0.14em] text-muted-ink">
            <MapIcon className="size-4 text-heat" aria-hidden="true" /> Corridor view
          </p>
          <h2 id="map-title" className="mt-1 text-base font-extrabold tracking-[-0.02em]">
            Thermal exposure + stop candidates
          </h2>
          <p className="mt-1 text-xs leading-5 text-muted-ink">
            {heatmap?.features.length
              ? `${heatmap.features.length} FortyGuard heat polygons · ${modeLabel(runtimeMode ?? 'DEMO_FIXTURE')}`
              : 'Stop-level heat until the heatmap layer arrives.'}
          </p>
        </div>
        <a href="#stops-table" className="pointer-events-auto app-link inline-flex min-h-11 items-center gap-2 bg-panel/95 px-3 text-xs shadow-sm">
          <Keyboard className="size-4" aria-hidden="true" /> Use table equivalent
        </a>
      </div>

      {mapFailed ? (
        <div className="grid min-h-[31rem] place-items-center p-8">
          <div className="max-w-sm text-center">
            <TriangleAlert className="mx-auto mb-4 text-danger" aria-hidden="true" />
            <h2 className="text-lg font-bold">Map rendering is unavailable</h2>
            <p className="mt-2 text-sm text-muted-ink">
              The synchronized stop table remains fully usable for review and selection.
            </p>
            <a href="#stops-table" className="app-link mt-4 inline-block">
              Continue in stop table
            </a>
          </div>
        </div>
      ) : (
        <div ref={containerRef} className="min-h-[31rem] w-full" aria-label="Interactive corridor map" />
      )}

      <div className="pointer-events-none absolute inset-x-0 bottom-0 z-10 flex flex-wrap gap-x-4 gap-y-2 border-t border-line bg-panel/95 px-4 py-3 text-[0.6875rem] font-semibold text-muted-ink">
        <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-full border-2 border-ink bg-panel" /> Recommended</span>
        <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-full border border-ink bg-sun" /> Candidate</span>
        <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-full bg-[#909991]" /> Existing shelter</span>
        <span className="ml-auto">Heat color = exceedance hours</span>
      </div>
    </section>
  )
}
