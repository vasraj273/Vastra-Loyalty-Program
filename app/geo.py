"""Indian city -> (lat, lng) lookup for map plotting.

Retailer regions are free-text city names; coordinates are resolved at
registration time so the admin panel can plot scans without geocoding
services. City-level precision is enough for the dashboard map.
"""

CITY_COORDS: dict[str, tuple[float, float]] = {
    "agra": (27.1767, 78.0081),
    "ahmedabad": (23.0225, 72.5714),
    "ajmer": (26.4499, 74.6399),
    "aligarh": (27.8974, 78.0880),
    "allahabad": (25.4358, 81.8463),
    "prayagraj": (25.4358, 81.8463),
    "amritsar": (31.6340, 74.8723),
    "aurangabad": (19.8762, 75.3433),
    "bareilly": (28.3670, 79.4304),
    "bengaluru": (12.9716, 77.5946),
    "bangalore": (12.9716, 77.5946),
    "bhavnagar": (21.7645, 72.1519),
    "bhilai": (21.1938, 81.3509),
    "bhopal": (23.2599, 77.4126),
    "bhubaneswar": (20.2961, 85.8245),
    "bikaner": (28.0229, 73.3119),
    "chandigarh": (30.7333, 76.7794),
    "chennai": (13.0827, 80.2707),
    "coimbatore": (11.0168, 76.9558),
    "cuttack": (20.4625, 85.8830),
    "dehradun": (30.3165, 78.0322),
    "delhi": (28.7041, 77.1025),
    "new delhi": (28.6139, 77.2090),
    "dhanbad": (23.7957, 86.4304),
    "durgapur": (23.5204, 87.3119),
    "erode": (11.3410, 77.7172),
    "faridabad": (28.4089, 77.3178),
    "firozabad": (27.1592, 78.3957),
    "ghaziabad": (28.6692, 77.4538),
    "gorakhpur": (26.7606, 83.3732),
    "guntur": (16.3067, 80.4365),
    "gurgaon": (28.4595, 77.0266),
    "gurugram": (28.4595, 77.0266),
    "guwahati": (26.1445, 91.7362),
    "gwalior": (26.2183, 78.1828),
    "howrah": (22.5958, 88.2636),
    "hubli": (15.3647, 75.1240),
    "hyderabad": (17.3850, 78.4867),
    "indore": (22.7196, 75.8577),
    "jabalpur": (23.1815, 79.9864),
    "jaipur": (26.9124, 75.7873),
    "jalandhar": (31.3260, 75.5762),
    "jammu": (32.7266, 74.8570),
    "jamnagar": (22.4707, 70.0577),
    "jamshedpur": (22.8046, 86.2029),
    "jhansi": (25.4484, 78.5685),
    "jodhpur": (26.2389, 73.0243),
    "kanpur": (26.4499, 80.3319),
    "karimnagar": (18.4386, 79.1288),
    "kochi": (9.9312, 76.2673),
    "kolhapur": (16.7050, 74.2433),
    "kolkata": (22.5726, 88.3639),
    "kota": (25.2138, 75.8648),
    "kozhikode": (11.2588, 75.7804),
    "lucknow": (26.8467, 80.9462),
    "ludhiana": (30.9010, 75.8573),
    "madurai": (9.9252, 78.1198),
    "mangalore": (12.9141, 74.8560),
    "meerut": (28.9845, 77.7064),
    "moradabad": (28.8386, 78.7733),
    "mumbai": (19.0760, 72.8777),
    "mysore": (12.2958, 76.6394),
    "mysuru": (12.2958, 76.6394),
    "nagpur": (21.1458, 79.0882),
    "nashik": (19.9975, 73.7898),
    "nellore": (14.4426, 79.9865),
    "noida": (28.5355, 77.3910),
    "panipat": (29.3909, 76.9635),
    "patiala": (30.3398, 76.3869),
    "patna": (25.5941, 85.1376),
    "puducherry": (11.9416, 79.8083),
    "pune": (18.5204, 73.8567),
    "raipur": (21.2514, 81.6296),
    "rajkot": (22.3039, 70.8022),
    "ranchi": (23.3441, 85.3096),
    "rourkela": (22.2604, 84.8536),
    "salem": (11.6643, 78.1460),
    "siliguri": (26.7271, 88.3953),
    "solapur": (17.6599, 75.9064),
    "srinagar": (34.0837, 74.7973),
    "surat": (21.1702, 72.8311),
    "thane": (19.2183, 72.9781),
    "thiruvananthapuram": (8.5241, 76.9366),
    "tiruchirappalli": (10.7905, 78.7047),
    "tirupati": (13.6288, 79.4192),
    "tiruppur": (11.1085, 77.3411),
    "udaipur": (24.5854, 73.7125),
    "ujjain": (23.1765, 75.7885),
    "vadodara": (22.3072, 73.1812),
    "varanasi": (25.3176, 82.9739),
    "vellore": (12.9165, 79.1325),
    "vijayawada": (16.5062, 80.6480),
    "visakhapatnam": (17.6868, 83.2185),
    "warangal": (17.9689, 79.5941),
    # States / union territories (centroids) so a state name still lands a
    # dot on the map when someone types "Assam" instead of "Guwahati".
    "andhra pradesh": (15.9129, 79.7400),
    "arunachal pradesh": (28.2180, 94.7278),
    "assam": (26.2006, 92.9376),
    "bihar": (25.0961, 85.3131),
    "chhattisgarh": (21.2787, 81.8661),
    "goa": (15.2993, 74.1240),
    "gujarat": (22.2587, 71.1924),
    "haryana": (29.0588, 76.0856),
    "himachal pradesh": (31.1048, 77.1734),
    "jharkhand": (23.6102, 85.2799),
    "karnataka": (15.3173, 75.7139),
    "kerala": (10.8505, 76.2711),
    "madhya pradesh": (22.9734, 78.6569),
    "maharashtra": (19.7515, 75.7139),
    "manipur": (24.6637, 93.9063),
    "meghalaya": (25.4670, 91.3662),
    "mizoram": (23.1645, 92.9376),
    "nagaland": (26.1584, 94.5624),
    "odisha": (20.9517, 85.0985),
    "punjab": (31.1471, 75.3412),
    "rajasthan": (27.0238, 74.2179),
    "sikkim": (27.5330, 88.5122),
    "tamil nadu": (11.1271, 78.6569),
    "telangana": (18.1124, 79.0193),
    "tripura": (23.9408, 91.9882),
    "uttar pradesh": (26.8467, 80.9462),
    "uttarakhand": (30.0668, 79.0193),
    "west bengal": (22.9868, 87.8550),
    "jammu and kashmir": (33.7782, 76.5762),
    "ladakh": (34.1526, 77.5771),
}


def known_places() -> list[str]:
    return sorted(CITY_COORDS.keys())


def coords_for(region: str) -> tuple[float, float] | None:
    return CITY_COORDS.get(region.strip().lower())


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    from math import radians, sin, cos, asin, sqrt
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = (sin(dlat / 2) ** 2
         + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2)
    return 2 * 6371.0 * asin(sqrt(a))


def nearest_city(lat: float, lng: float) -> str | None:
    """Reverse-geocode coordinates to the closest known place (offline,
    city-level precision). Used to infer a retailer's region from where they
    first scan when no city was entered at registration. Returned in Title
    Case to match how manufacturers type city names."""
    best, best_d = None, None
    for name, (clat, clng) in CITY_COORDS.items():
        d = _haversine_km(lat, lng, clat, clng)
        if best_d is None or d < best_d:
            best, best_d = name, d
    return best.title() if best else None


def reverse_address(lat: float, lng: float) -> str | None:
    """Best-effort reverse geocode to a full readable street address via
    OpenStreetMap's free Nominatim service (no API key). Returns e.g.
    "Naroda Business Hub, Naroda - Dehgam Road, Naroda, Ahmedabad, Gujarat,
    382330, India", or None on any failure (caller falls back to the city /
    the map link, which always works from the raw coordinates).

    Called ~once per scanning session, with a short timeout and an identifying
    User-Agent, to respect Nominatim's usage policy."""
    import json
    import urllib.parse
    import urllib.request
    url = "https://nominatim.openstreetmap.org/reverse?" + urllib.parse.urlencode(
        {"format": "jsonv2", "lat": lat, "lon": lng,
         "zoom": 18, "addressdetails": 0})
    req = urllib.request.Request(
        url, headers={"User-Agent": "VastraLoyalty/1.0 (retailer loyalty app)"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.load(resp)
        name = (data.get("display_name") or "").strip()
        return name or None
    except Exception:
        return None
