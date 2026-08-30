import { useEffect, useMemo, useRef, useState } from 'react'
import * as maplibregl from 'maplibre-gl'
import type { GeoJSONSource, Map as MapLibreMap, MapLayerMouseEvent, StyleSpecification } from 'maplibre-gl'
import maplibreWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url'
import { Keyboard, Map as MapIcon, TriangleAlert } from 'lucide-react'
import type { Stop } from '../data/fixture'
import type { HeatmapLayer } from '../lib/api'
import { modeLabel } from '../lib/api'
import { portfolioRankById, selectedReason } from '../lib/planning'
import { formatNumber } from '../lib/utils'

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
        shelterCount: stop.shelterCount,
        rank: stop.rank ?? 0,
        heat: stop.exceedanceHours,
        ridership: stop.ridershipValue,
      },
    })),
  }
}

function shelterStatus(stop: Stop) {
  if (stop.shelterCount > 0) return `Existing shelter (${stop.shelterCount} on site)`
  if (stop.selected) return 'Recommended new shelter'
  return 'No new shelter in this portfolio'
}

function asStopId(value: unknown): string | null {
  if (typeof value === 'string' && value) return value
  if (typeof value === 'number' && Number.isFinite(value)) return String(value)
  return null
}

function markerLabel(stop: Stop, pinRank?: number) {
  if (stop.selected) return String(pinRank ?? stop.rank ?? '')
  if (stop.shelterCount > 0) return `S${stop.shelterCount}`
  return '·'
}

function popupHtml(stop: Stop, pinRank?: number) {
  const pin = pinRank ? `Pin ${pinRank}` : 'Stop'
  return `
    <strong>${escapeHtml(stop.name)}</strong>
    <div>${pin} · ${escapeHtml(shelterStatus(stop))}</div>
    <div>${stop.exceedanceHours.toFixed(1)} hot hours · ${formatNumber(stop.ridershipValue)} waiting</div>
    <div>Neighborhood ${Math.round(stop.sviPercentile * 100)}th · ${escapeHtml(stop.stopId)}</div>
  `
}

function SelectedStopCard({ stop, pinRank }: { stop: Stop; pinRank?: number }) {
  return (
    <article
      id="map-stop-details"
      className="pointer-events-auto border border-ink bg-panel shadow-[4px_4px_0_rgba(20,41,37,0.18)]"
      aria-live="polite"
      aria-label="Selected stop details"
    >
      <div className="thermal-rule" />
      <div className="px-3 py-2.5 sm:px-4">
        <p className="text-[0.65rem] font-bold uppercase tracking-[0.12em] text-heat">
          {pinRank ? `Pin ${pinRank}` : 'Selected stop'} · {shelterStatus(stop)}
        </p>
        <h3 className="mt-1 text-sm font-extrabold leading-5 tracking-[-0.02em] sm:text-base">{stop.name}</h3>
        <p className="mt-0.5 font-mono text-[0.68rem] text-muted-ink">
          {stop.stopId}
          {stop.selected ? ` · ${selectedReason(stop)}` : ''}
        </p>
        <dl className="mt-2 grid grid-cols-3 gap-2 border-t border-line pt-2">
          <div>
            <dt className="text-[0.62rem] font-bold uppercase tracking-[0.1em] text-muted-ink">Hot hours</dt>
            <dd className="metric-numeral text-sm font-extrabold sm:text-base">{stop.exceedanceHours.toFixed(1)}</dd>
          </div>
          <div>
            <dt className="text-[0.62rem] font-bold uppercase tracking-[0.1em] text-muted-ink">Waiting</dt>
            <dd className="metric-numeral text-sm font-extrabold sm:text-base">{formatNumber(stop.ridershipValue)}</dd>
          </div>
          <div>
            <dt className="text-[0.62rem] font-bold uppercase tracking-[0.1em] text-muted-ink">Neighborhood</dt>
            <dd className="metric-numeral text-sm font-extrabold sm:text-base">{Math.round(stop.sviPercentile * 100)}th</dd>
          </div>
        </dl>
      </div>
    </article>
  )
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
  const markersRef = useRef<maplibregl.Marker[]>([])
  const popupRef = useRef<maplibregl.Popup | null>(null)
  const onSelectRef = useRef(onSelect)
  const focusedStopIdRef = useRef<string | null>(null)
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
            'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
          ],
          tileSize: 256,
          attribution: '© OpenStreetMap contributors · FortyGuard heat surface',
          maxzoom: 19,
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
            'fill-opacity': 0.26,
          },
        },
        {
          id: 'heat-polygons-line',
          type: 'line',
          source: 'heatPolygons',
          paint: { 'line-color': '#7a241c', 'line-width': 0.4, 'line-opacity': 0.35 },
        },
        {
          id: 'stops-halo',
          type: 'circle',
          source: 'stops',
          paint: {
            'circle-radius': [
              'case',
              ['==', ['get', 'selected'], 1], 16,
              ['==', ['get', 'recommended'], 1], 0,
              ['==', ['get', 'existingShelter'], 1], 0,
              12,
            ],
            'circle-color': '#fffdf7',
            'circle-opacity': 0.92,
          },
        },
        {
          id: 'stops-layer',
          type: 'circle',
          source: 'stops',
          paint: {
            'circle-radius': [
              'case',
              ['==', ['get', 'selected'], 1], 8,
              ['==', ['get', 'recommended'], 1], 0,
              ['==', ['get', 'existingShelter'], 1], 0,
              6.5,
            ],
            'circle-color': '#c48a12',
            'circle-stroke-color': '#142925',
            'circle-stroke-width': 1.25,
            'circle-opacity': 0.92,
          },
        },
      ],
    }

    const canvasProbe = document.createElement('canvas')
    let hasWebGl = false
    try {
      hasWebGl = Boolean(canvasProbe.getContext('webgl2') || canvasProbe.getContext('webgl'))
    } catch {
      hasWebGl = false
    }
    if (!hasWebGl) {
      setMapFailed(true)
      return
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
      popupRef.current = new maplibregl.Popup({
        closeButton: true,
        closeOnClick: false,
        offset: 32,
        className: 'stop-popup',
        maxWidth: '280px',
      })

      map.on('load', () => {
        map.resize()
        setMapReady(true)
      })
      map.on('click', 'stops-layer', (event: MapLayerMouseEvent) => {
        const stopId = asStopId(event.features?.[0]?.properties?.stopId)
        if (stopId) onSelectRef.current(stopId)
      })
      map.on('click', 'stops-halo', (event: MapLayerMouseEvent) => {
        const stopId = asStopId(event.features?.[0]?.properties?.stopId)
        if (stopId) onSelectRef.current(stopId)
      })
      map.on('mouseenter', 'stops-layer', () => {
        map.getCanvas().style.cursor = 'pointer'
      })
      map.on('mouseleave', 'stops-layer', () => {
        map.getCanvas().style.cursor = ''
      })
      map.on('error', () => setMapFailed(true))
      map.getCanvas().addEventListener('webglcontextlost', () => setMapFailed(true), { once: true })
      mapRef.current = map
    } catch (error) {
      console.error('MapLibre initialization failed', error)
      queueMicrotask(() => setMapFailed(true))
    }

    const observer = new ResizeObserver(() => {
      try {
        mapRef.current?.resize()
      } catch {
        setMapFailed(true)
      }
    })
    if (containerRef.current) observer.observe(containerRef.current)

    return () => {
      observer.disconnect()
      for (const marker of markersRef.current) {
        try {
          marker.remove()
        } catch {
          /* jsdom and lost WebGL have no painter to destroy */
        }
      }
      markersRef.current = []
      try {
        popupRef.current?.remove()
      } catch {
        /* popup may already be detached */
      }
      try {
        mapRef.current?.remove()
      } catch {
        /* MapLibre cannot destroy a painter-less map */
      }
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

    for (const marker of markersRef.current) marker.remove()
    const pinRanks = portfolioRankById(stops)
    const pinStops = stops.filter((stop) => stop.selected || stop.shelterCount > 0)
    markersRef.current = pinStops.map((stop) => {
      const pin = document.createElement('button')
      pin.type = 'button'
      const kind = stop.shelterCount > 0 ? 'existing' : stop.selected ? 'new' : 'candidate'
      pin.className = `shelter-pin shelter-pin-${kind}${stop.stopId === selectedStopId ? ' shelter-pin-selected' : ''}`
      pin.textContent = markerLabel(stop, pinRanks.get(stop.stopId))
      pin.setAttribute(
        'aria-label',
        `${stop.name}. ${shelterStatus(stop)}. ${stop.exceedanceHours.toFixed(1)} exceedance hours.`,
      )
      pin.addEventListener('click', (event) => {
        event.stopPropagation()
        onSelectRef.current(stop.stopId)
        popupRef.current
          ?.setLngLat([stop.longitude, stop.latitude])
          .setHTML(popupHtml(stop, pinRanks.get(stop.stopId)))
          .addTo(map)
      })
      return new maplibregl.Marker({ element: pin, anchor: 'bottom' })
        .setLngLat([stop.longitude, stop.latitude])
        .addTo(map)
    })
    const selected = stops.find((item) => item.stopId === selectedStopId)
    if (selected) {
      popupRef.current
        ?.setLngLat([selected.longitude, selected.latitude])
        .setHTML(popupHtml(selected, pinRanks.get(selected.stopId)))
        .addTo(map)
    }

    return () => {
      for (const marker of markersRef.current) marker.remove()
      markersRef.current = []
    }
  }, [mapReady, selectedStopId, stops])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapReady || !selectedStopId) return
    if (focusedStopIdRef.current === null) {
      focusedStopIdRef.current = selectedStopId
      return
    }
    if (focusedStopIdRef.current === selectedStopId) return
    focusedStopIdRef.current = selectedStopId
    const stop = stops.find((item) => item.stopId === selectedStopId)
    if (!stop) return
    map.easeTo({
      center: [stop.longitude, stop.latitude],
      zoom: Math.max(map.getZoom(), 14.2),
      duration: 700,
    })
    popupRef.current
      ?.setLngLat([stop.longitude, stop.latitude])
      .setHTML(popupHtml(stop, portfolioRankById(stops).get(stop.stopId)))
      .addTo(map)
  }, [mapReady, selectedStopId, stops])

  const lowLabel = `${range.min.toFixed(range.min >= 100 ? 0 : 1)} h`
  const highLabel = `${range.max.toFixed(range.max >= 100 ? 0 : 1)} h`
  const pinRanks = portfolioRankById(stops)
  const selectedStop = stops.find((stop) => stop.stopId === selectedStopId)
  const selectedPin = selectedStop ? pinRanks.get(selectedStop.stopId) : undefined

  return (
    <section id="corridor-map" className="border border-line bg-[#d7d2c4]" aria-labelledby="map-title">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line bg-panel px-4 py-3">
        <div className="max-w-xl">
          <p className="flex items-center gap-2 text-xs font-bold uppercase tracking-[0.14em] text-muted-ink">
            <MapIcon className="size-4 text-heat" aria-hidden="true" /> Phoenix corridor
          </p>
          <h2 id="map-title" className="mt-1 text-base font-extrabold tracking-[-0.02em]">
            Recommended pins on the heat surface
          </h2>
          <p className="mt-1 text-xs leading-5 text-muted-ink">
            Numbered pins 1–{Math.max(1, stops.filter((stop) => stop.selected).length)} are new shelters.
            Click a pin or a table row to read that stop on the map.
            Dots are other official Phoenix stops.
            {heatCount
              ? ` ${heatCount.toLocaleString('en-US')} FortyGuard cells · ${stops.length} stops · ${modeLabel(runtimeMode ?? 'DEMO_FIXTURE')}`
              : ` ${stops.length} stops`}
          </p>
        </div>
        <a href="#stops-table" className="app-link inline-flex min-h-11 items-center gap-2 px-3 text-xs">
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
        <div className="relative h-[min(70vh,38rem)] min-h-[26rem] w-full overflow-hidden">
          <div ref={containerRef} className="absolute inset-0 h-full w-full" aria-label="Interactive corridor map" />
          {selectedStop ? (
            <div className="pointer-events-none absolute inset-x-3 top-3 z-10 max-w-lg sm:right-14">
              <SelectedStopCard stop={selectedStop} pinRank={selectedPin} />
            </div>
          ) : null}
        </div>
      )}

      {mapFailed && selectedStop ? (
        <div className="border-t border-line bg-panel p-3">
          <SelectedStopCard stop={selectedStop} pinRank={selectedPin} />
        </div>
      ) : null}

      <div className="border-t border-line bg-panel px-4 py-3">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="min-w-[12rem] flex-1">
            <p className="text-[0.65rem] font-bold uppercase tracking-[0.12em] text-muted-ink">Hot hours</p>
            <div className="mt-1.5 h-2 rounded-sm bg-[linear-gradient(90deg,#f6de8a,#e08a3c,#c2462f,#6d1b1b)]" aria-hidden="true" />
            <div className="mt-1 flex justify-between font-mono text-[0.65rem] font-bold">
              <span>{lowLabel}</span>
              <span>{highLabel}</span>
            </div>
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-2 text-[0.6875rem] font-semibold text-muted-ink">
            <span className="flex items-center gap-1.5"><span className="grid size-5 place-items-center rounded-full bg-action text-[0.6rem] font-extrabold text-white">1</span> New shelter (rank)</span>
            <span className="flex items-center gap-1.5"><span className="grid size-5 place-items-center rounded-sm bg-[#4d5552] text-[0.55rem] font-extrabold text-white">S</span> Existing shelter</span>
            <span className="flex items-center gap-1.5"><span className="size-5 rounded-full bg-[#c48a12]" /> No new shelter</span>
          </div>
        </div>
      </div>
    </section>
  )
}
