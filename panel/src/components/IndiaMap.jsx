import { useEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

const INDIA_CENTER = [22.8, 80.5]

export default function IndiaMap({ points }) {
  const divRef = useRef(null)
  const mapRef = useRef(null)
  const layerRef = useRef(null)

  useEffect(() => {
    if (!mapRef.current) {
      const map = L.map(divRef.current, {
        center: INDIA_CENTER,
        zoom: 5,
        minZoom: 4,
        maxZoom: 12,
        scrollWheelZoom: true,
      })
      L.tileLayer(
        'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
        {
          attribution:
            '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
          subdomains: 'abcd',
        },
      ).addTo(map)
      mapRef.current = map
      layerRef.current = L.layerGroup().addTo(map)
    }

    const layer = layerRef.current
    layer.clearLayers()
    const maxScans = Math.max(1, ...points.map((p) => p.scans))
    points.forEach((p) => {
      const radius = 6 + 14 * Math.sqrt(p.scans / maxScans)
      const marker = L.circleMarker([p.lat, p.lng], {
        radius,
        color: '#b8431f',
        weight: 1.5,
        fillColor: '#c8472b',
        fillOpacity: 0.55,
      })
      marker.bindTooltip(
        `<div class="map-tip">
           <strong>${p.shop_name}</strong>
           <span>${p.name} · ${p.region}</span>
           <span>${p.scans} scans · ${p.points} points</span>
           <span class="tip-sub">last scan ${p.last_scan}</span>
         </div>`,
        { sticky: true, direction: 'top', opacity: 1 },
      )
      marker.addTo(layer)
    })

    return undefined
  }, [points])

  useEffect(
    () => () => {
      if (mapRef.current) {
        mapRef.current.remove()
        mapRef.current = null
      }
    },
    [],
  )

  return <div ref={divRef} className="india-map" />
}
