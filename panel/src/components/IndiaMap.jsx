import { useEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import 'leaflet.markercluster'
import 'leaflet.markercluster/dist/MarkerCluster.css'
import 'leaflet.markercluster/dist/MarkerCluster.Default.css'

const INDIA_CENTER = [22.8, 80.5]

// A scan dot as a divIcon (markercluster only clusters L.marker, not circleMarker)
// sized by scan volume, matching the panel's terracotta palette.
function dotIcon(scans, maxScans) {
  const d = Math.round(2 * (6 + 14 * Math.sqrt(scans / maxScans)))
  return L.divIcon({
    className: 'scan-dot-icon',
    html: `<span class="scan-dot" style="width:${d}px;height:${d}px"></span>`,
    iconSize: [d, d],
    iconAnchor: [d / 2, d / 2],
  })
}

export default function IndiaMap({ points }) {
  const divRef = useRef(null)
  const mapRef = useRef(null)
  const clusterRef = useRef(null)

  useEffect(() => {
    if (!mapRef.current) {
      const map = L.map(divRef.current, {
        center: INDIA_CENTER,
        zoom: 5,
        minZoom: 4,
        maxZoom: 18,
        scrollWheelZoom: true,
      })
      L.tileLayer(
        'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
        {
          attribution:
            '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
          subdomains: 'abcd',
          maxZoom: 19,
        },
      ).addTo(map)
      mapRef.current = map
      clusterRef.current = L.markerClusterGroup({
        maxClusterRadius: 45,
        showCoverageOnHover: false,
        spiderfyOnMaxZoom: true,
        chunkedLoading: true,
      }).addTo(map)
    }

    const cluster = clusterRef.current
    cluster.clearLayers()
    const maxScans = Math.max(1, ...points.map((p) => p.scans))
    points.forEach((p) => {
      const marker = L.marker([p.lat, p.lng], { icon: dotIcon(p.scans, maxScans) })
      marker.bindTooltip(
        `<div class="map-tip">
           <strong>${p.shop_name}</strong>
           <span>${p.name} · ${p.region}</span>
           <span>${p.scans} scans · ${p.points} points</span>
           <span class="tip-sub">last scan ${p.last_scan}</span>
         </div>`,
        { sticky: true, direction: 'top', opacity: 1 },
      )
      cluster.addLayer(marker)
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
