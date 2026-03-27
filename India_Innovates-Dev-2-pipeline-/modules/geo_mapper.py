"""
Phase 10 — Geo-Coordinate Mapping
Maps intersection IDs to geographic coordinates (latitude, longitude).
Provides pixel-to-geo coordinate conversion for vehicle tracking.
"""

from typing import Dict, Tuple, Optional


class GeoMapper:
    """
    Maps between pixel coordinates and geographic coordinates.
    
    Uses linear interpolation based on known intersection positions
    to convert vehicle pixel positions to approximate geo-coordinates.
    """

    def __init__(self, intersections_geo: Dict[str, dict], image_size: Tuple[int, int]):
        """
        Args:
            intersections_geo: dict of intersection_id -> {name, latitude, longitude}
            image_size: (width, height) of the camera frame in pixels
        """
        self.geo_data = intersections_geo
        self.image_width, self.image_height = image_size

        # Compute bounding box of geo-coordinates for pixel interpolation
        lats = [info["latitude"] for info in intersections_geo.values()]
        lons = [info["longitude"] for info in intersections_geo.values()]

        if lats and lons:
            self.min_lat = min(lats)
            self.max_lat = max(lats)
            self.min_lon = min(lons)
            self.max_lon = max(lons)

            # Add some padding for the camera view
            lat_range = self.max_lat - self.min_lat or 0.001
            lon_range = self.max_lon - self.min_lon or 0.001
            self.min_lat -= lat_range * 0.2
            self.max_lat += lat_range * 0.2
            self.min_lon -= lon_range * 0.2
            self.max_lon += lon_range * 0.2
        else:
            # Default fallback
            self.min_lat = 21.14
            self.max_lat = 21.16
            self.min_lon = 79.08
            self.max_lon = 79.10

    def get_intersection_geo(self, intersection_id: str) -> Optional[Tuple[float, float]]:
        """Get (latitude, longitude) for an intersection."""
        info = self.geo_data.get(intersection_id)
        if info:
            return (info["latitude"], info["longitude"])
        return None

    def pixel_to_geo(self, pixel_x: int, pixel_y: int) -> Tuple[float, float]:
        """
        Convert pixel coordinates to approximate geographic coordinates.
        
        Uses linear interpolation:
        - x=0 corresponds to min_lon, x=image_width corresponds to max_lon
        - y=0 corresponds to max_lat (top), y=image_height corresponds to min_lat (bottom)
        
        Returns:
            (latitude, longitude) tuple
        """
        # Longitude: left to right
        lon = self.min_lon + (pixel_x / self.image_width) * (self.max_lon - self.min_lon)

        # Latitude: top to bottom (inverted — higher lat at top)
        lat = self.max_lat - (pixel_y / self.image_height) * (self.max_lat - self.min_lat)

        return (round(lat, 6), round(lon, 6))

    def geo_to_pixel(self, lat: float, lon: float) -> Tuple[int, int]:
        """
        Convert geographic coordinates to pixel coordinates (inverse mapping).
        
        Returns:
            (pixel_x, pixel_y) tuple
        """
        pixel_x = int(
            (lon - self.min_lon) / (self.max_lon - self.min_lon) * self.image_width
        )
        pixel_y = int(
            (self.max_lat - lat) / (self.max_lat - self.min_lat) * self.image_height
        )

        # Clamp to image bounds
        pixel_x = max(0, min(pixel_x, self.image_width - 1))
        pixel_y = max(0, min(pixel_y, self.image_height - 1))

        return (pixel_x, pixel_y)

    def get_all_intersections(self) -> Dict[str, Tuple[float, float]]:
        """Get all intersection geo-coordinates."""
        return {
            int_id: (info["latitude"], info["longitude"])
            for int_id, info in self.geo_data.items()
        }
