"""Spherical great-circle segment distances in km, including the date line.
Mean Earth radius approximation, not survey-grade ellipsoidal navigation.
"""
import math
EARTH_RADIUS_KM = 6371.0088

def validate_point(lat, lon):
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (lat, lon)) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError('Invalid geographic coordinates')

def haversine_distance_km(lat1, lon1, lat2, lon2):
    validate_point(lat1, lon1); validate_point(lat2, lon2)
    a = math.sin(math.radians(lat2-lat1)/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(math.radians(lon2-lon1)/2)**2
    return 2*EARTH_RADIUS_KM*math.asin(math.sqrt(max(0, min(1, a))))

def bearing(a, b, c, d):
    p, q, delta = math.radians(a), math.radians(c), math.radians(d-b)
    return math.atan2(math.sin(delta)*math.cos(q), math.cos(p)*math.sin(q)-math.sin(p)*math.cos(q)*math.cos(delta))

def point_to_segment_distance_km(p_lat, p_lon, a_lat, a_lon, b_lat, b_lon, samples=10):
    da = haversine_distance_km(a_lat, a_lon, p_lat, p_lon)/EARTH_RADIUS_KM
    length = haversine_distance_km(a_lat, a_lon, b_lat, b_lon)/EARTH_RADIUS_KM
    ends = min(da*EARTH_RADIUS_KM, haversine_distance_km(b_lat,b_lon,p_lat,p_lon))
    if length < 1e-12: return ends
    if length >= math.pi-1e-8: raise ValueError('Antipodal segment is ambiguous')
    delta = bearing(a_lat,a_lon,p_lat,p_lon)-bearing(a_lat,a_lon,b_lat,b_lon)
    along = math.atan2(math.sin(da)*math.cos(delta), math.cos(da))
    cross = math.asin(max(-1, min(1, math.sin(da)*math.sin(delta))))
    return abs(cross)*EARTH_RADIUS_KM if 0 <= along <= length else ends

def point_to_linestring_distance_km(lat, lon, coords):
    validate_point(lat,lon)
    if not isinstance(coords, list) or len(coords) < 2: raise ValueError('LineString needs at least two coordinates')
    for point in coords:
        if not isinstance(point,(list,tuple)) or len(point)!=2: raise ValueError('Expected [longitude, latitude]')
        validate_point(point[1], point[0])
    return min(point_to_segment_distance_km(lat,lon,a[1],a[0],b[1],b[0]) for a,b in zip(coords,coords[1:]))
