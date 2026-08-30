import { useEffect, useMemo, useRef, useState } from 'react'
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

const emptyHeat: HeatmapLayer = { type: 'FeatureCollection', features: [] }

function asNumber(value: unknown, fallback = 0) {
  const parsed = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

function escapeHtml(value: string) {
  return value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;')
}

function numericHeatmap(layer: HeatmapLayer | null | undefined): HeatmapLayer {
  if (!layer?.features?.length) return emptyHeat
  return {
    type: 'FeatureCollection',
    features: layer.features.map((feature) => ({
      ...feature,
      properties: {
        ...feature.properties,
        value: asNumber(feature.properties?.value),
      },
    })),
  }
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
        name: stop.name,
        selected: stop.stopId === selectedStopId ? 1 : 0,
        recommended: stop.selected ? 1 : 0,
        baseline: stop.baselineSelected ? 1 : 0,
        existingShelter: stop.shelterCount > 0 ? 1 : 0,
        heat: stop.exceedanceHours,
      },
    })),
  }
}

function heatRange(heatmap: HeatmapLayer, stops: Stop[]) {
  const fromCells = heatmap.features.map((feature) => asNumber(feature.properties?.value, Number.NaN))
  const fromStops = stops.map((stop) => stop.exceedanceHours)
  const values = (fromCells.some((value) => Number.isFinite(value)) ? fromCells : fromStops).filter((value) =>
    Number.isFinite(value),
  )
  if (values.length === 0) return { min: 0, max: 1 }
  const min = Math.min(...values)
  const max = Math.max(...values)
  if (max - min < 0.01) return { min: min * 0.92, max: max * 1.08 || 1 }
  return { min, max }
}

function heatFillColor(min: number, max: number) {
  const span = max - min
  return [
    'interpolate',
    ['linear'],
    ['to-number', ['coalesce', ['get', 'value'], 0]],
    min,
    '#f6de8a',
    min + span * 0.35,
    '#e08a3c',
    min + span * 0.7,
    '#c2462f',
    max,
    '#6d1b1b',
  ]
}

export function CorridorMap({ stops, selectedStopId, onSelect, heatmap, runtimeMode }: CorridorMapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<MapLibreMap | null>(null)
  const popupRef = useRef<maplibregl.Popup | null>(null)
  const onSelectRef = useRef(onSelect)
  const [mapReady, setMapReady] = useState(false)
  const [mapFailed, setMapFailed] = useState(false)
  const layer = useMemo(() => numericHeatmap(heatmap), [heatmap])
  const range = useMemo(() => heatRange(layer, stops), [layer, stops])
  const heatCount = layer.features.length

  useEffect(() => {
    onSelectRef.current = onSelect
  }, [onSelect])

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return

    const style: StyleSpecification = {
      version: 8,
      sources: {
        basemap: {
          type: 'raster',
          tiles: [
            'https://a.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}@2x.png',
            'https://b.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}@2x.png',
            'https://c.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}@2x.png',
          ],
          tileSize: 256,
          attribution: '© OpenStreetMap © CARTO',
          maxzoom: 20,
        },
        heatPolygons: { type: 'geojson', data: emptyHeat },
        stops: { type: 'geojson', data: stopCollection([], '') },
      },
      layers: [
        { id: 'basemap', type: 'raster', source: 'basemap' },
        {
          id: 'heat-polygons-fill',
          type: 'fill',
          source: 'heatPolygons',
          paint: {
            'fill-color': heatFillColor(range.min, range.max) as never,
            'fill-opacity': 0.58,
          },
        },
        {
          id: 'heat-polygons-line',
          type: 'line',
          source: 'heatPolygons',
          paint: { 'line-color': '#7a241c', 'line-width': 0.4, 'line-opacity': 0.35 },
        },
        {
          id: 'stops-layer',
          type: 'circle',
          source: 'stops',
          paint: {
            'circle-radius': ['case', ['==', ['get', 'selected'], 1], 10, ['==', ['get', 'recommended'], 1], 8, 6],
            'circle-color': [
              'case',
              ['==', ['get', 'selected'], 1],
              '#062e2a',
              ['==', ['get', 'existingShelter'], 1],
              '#6d7672',
              ['==', ['get', 'recommended'], 1],
              '#0e6159',
              '#e2a52b',
            ],
            'circle-stroke-color': '#fffdf7',
            'circle-stroke-width': ['case', ['==', ['get', 'selected'], 1], 3, 2],
          },
        },
      ],
    }

    try {
      const map = new maplibregl.Map({
        container: containerRef.current,
        style,
        center: [-112.078, 33.478],
        zoom: 12.2,
        attributionControl: { compact: true },
        cooperativeGestures: true,
      })
      map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')
      popupRef.current = new maplibregl.Popup({ closeButton: false, offset: 12, className: 'stop-popup' })

      map.on('load', () => {
        map.resize()
        setMapReady(true)
      })
      map.on('click', 'stops-layer', (event: MapLayerMouseEvent) => {
        const stopId = event.features?.[0]?.properties.stopId
        if (typeof stopId === 'string') onSelectRef.current(stopId)
      })
      map.on('mousemove', 'stops-layer', (event: MapLayerMouseEvent) => {
        map.getCanvas().style.cursor = 'pointer'
        const feature = event.features?.[0]
        if (!feature || !event.lngLat) return
        const name = escapeHtml(String(feature.properties?.name ?? feature.properties?.stopId ?? 'Stop'))
        const heat = asNumber(feature.properties?.heat)
        const rank = feature.properties?.recommended === 1 ? 'Recommended' : 'Candidate'
        popupRef.current
          ?.setLngLat(event.lngLat)
          .setHTML(
            `<strong>${name}</strong><div>${heat.toFixed(1)} exceedance hours</div><div>${rank}</div>`,
          )
          .addTo(map)
      })
      map.on('mouseleave', 'stops-layer', () => {
        map.getCanvas().style.cursor = ''
        popupRef.current?.remove()
      })
      map.getCanvas().addEventListener('webglcontextlost', () => setMapFailed(true), { once: true })
      mapRef.current = map
    } catch (error) {
      console.error('MapLibre initialization failed', error)
      queueMicrotask(() => setMapFailed(true))
    }

    const observer = new ResizeObserver(() => mapRef.current?.resize())
    if (containerRef.current) observer.observe(containerRef.current)

    return () => {
      observer.disconnect()
      popupRef.current?.remove()
      mapRef.current?.remove()
      mapRef.current = null
    }
    // Map is created once; later effects push data into sources.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapReady) return
    const heatSource = map.getSource('heatPolygons') as GeoJSONSource | undefined
    heatSource?.setData(layer)
    if (map.getLayer('heat-polygons-fill')) {
      map.setPaintProperty('heat-polygons-fill', 'fill-color', heatFillColor(range.min, range.max) as never)
    }
    map.resize()
    if (stops.length === 0) return
    const bounds = new maplibregl.LngLatBounds()
    for (const stop of stops) bounds.extend([stop.longitude, stop.latitude])
    if (!bounds.isEmpty()) {
      map.fitBounds(bounds, { padding: 72, maxZoom: 13.4, duration: 0 })
    }
  }, [layer, mapReady, range.max, range.min, stops])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapReady) return
    const stopSource = map.getSource('stops') as GeoJSONSource | undefined
    stopSource?.setData(stopCollection(stops, selectedStopId))
  }, [mapReady, selectedStopId, stops])

  const lowLabel = `${range.min.toFixed(range.min >= 100 ? 0 : 1)} h`
  const highLabel = `${range.max.toFixed(range.max >= 100 ? 0 : 1)} h`

  return (
    <section className="relative overflow-hidden border border-line bg-[#d7d2c4]" aria-labelledby="map-title">
      <div className="pointer-events-none absolute inset-x-0 top-0 z-10 flex flex-wrap items-start justify-between gap-3 p-4">
        <div className="pointer-events-auto max-w-[20rem] border border-line bg-panel/95 p-3 shadow-[4px_4px_0_rgba(20,41,37,0.12)]">
          <p className="flex items-center gap-2 text-xs font-bold uppercase tracking-[0.14em] text-muted-ink">
            <MapIcon className="size-4 text-heat" aria-hidden="true" /> Phoenix corridor
          </p>
          <h2 id="map-title" className="mt-1 text-base font-extrabold tracking-[-0.02em]">
            Heat polygons + recommended stops
          </h2>
          <p className="mt-1 text-xs leading-5 text-muted-ink">
            {heatCount
              ? `${heatCount.toLocaleString('en-US')} FortyGuard cells · ${modeLabel(runtimeMode ?? 'DEMO_FIXTURE')}`
              : 'Waiting for the heat surface.'}
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
        <div className="relative h-[min(70vh,38rem)] min-h-[26rem] w-full">
          <div ref={containerRef} className="absolute inset-0 h-full w-full" aria-label="Interactive corridor map" />
        </div>
      )}

      <div className="absolute inset-x-0 bottom-0 z-10 border-t border-line bg-panel/95 px-4 py-3">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="min-w-[12rem] flex-1">
            <p className="text-[0.65rem] font-bold uppercase tracking-[0.12em] text-muted-ink">Exceedance hours</p>
            <div className="mt-1.5 h-2 rounded-sm bg-[linear-gradient(90deg,#f6de8a,#e08a3c,#c2462f,#6d1b1b)]" aria-hidden="true" />
            <div className="mt-1 flex justify-between font-mono text-[0.65rem] font-bold">
              <span>{lowLabel}</span>
              <span>{highLabel}</span>
            </div>
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-2 text-[0.6875rem] font-semibold text-muted-ink">
            <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-full border-2 border-white bg-action" /> Recommended</span>
            <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-full bg-sun" /> Candidate</span>
            <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-full bg-[#6d7672]" /> Existing shelter</span>
          </div>
        </div>
      </div>
    </section>
  )
}
