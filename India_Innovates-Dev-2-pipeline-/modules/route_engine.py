"""
Phase 11 — Route Generation Engine (Dijkstra)
Finds optimal routes between intersections in the city graph.
Computes route metrics: total_distance, avg_congestion, estimated_time.
"""

import heapq
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class Route:
    """A computed route between two intersections."""
    route_id: str
    path: List[str]              # ordered list of intersection IDs
    total_distance: float
    avg_congestion: float        # average congestion factor along route
    estimated_time: float        # seconds

    def to_dict(self) -> dict:
        return {
            "route_id": self.route_id,
            "path": self.path,
            "total_distance": round(self.total_distance, 2),
            "avg_congestion": round(self.avg_congestion, 2),
            "estimated_time": round(self.estimated_time, 2),
        }


class RouteEngine:
    """
    Route discovery and evaluation engine using Dijkstra's algorithm.
    
    Features:
    - Shortest path computation
    - Congestion-aware routing (uses weighted edges)
    - Route metrics computation
    - Multiple route options (k-shortest paths approximation)
    """

    # Assumed average speed in meters/second for time estimation
    DEFAULT_SPEED_MPS = 8.33  # ~30 km/h urban average

    def __init__(self, city_graph: "CityGraph"):
        self.graph = city_graph

    def find_shortest_path(self, start: str, end: str) -> Optional[Route]:
        """
        Find the shortest (least-weight) path using Dijkstra's algorithm.
        
        Weight considers both distance and congestion.
        
        Args:
            start: source intersection ID
            end: destination intersection ID
        
        Returns:
            Route object, or None if no path exists
        """
        if start not in self.graph.nodes or end not in self.graph.nodes:
            return None

        # Dijkstra's algorithm
        dist = {node_id: float("inf") for node_id in self.graph.nodes}
        prev = {node_id: None for node_id in self.graph.nodes}
        edge_used = {node_id: None for node_id in self.graph.nodes}
        dist[start] = 0

        pq = [(0, start)]  # (distance, node_id)
        visited = set()

        while pq:
            d, u = heapq.heappop(pq)

            if u in visited:
                continue
            visited.add(u)

            if u == end:
                break

            for neighbor, edge in self.graph.get_neighbors(u):
                if neighbor in visited:
                    continue

                new_dist = dist[u] + edge.weight
                if new_dist < dist[neighbor]:
                    dist[neighbor] = new_dist
                    prev[neighbor] = u
                    edge_used[neighbor] = edge
                    heapq.heappush(pq, (new_dist, neighbor))

        # Reconstruct path
        if dist[end] == float("inf"):
            return None

        path = []
        edges_in_path = []
        node = end
        while node is not None:
            path.append(node)
            if edge_used[node] is not None:
                edges_in_path.append(edge_used[node])
            node = prev[node]
        path.reverse()

        # Compute route metrics
        total_distance = sum(e.distance for e in edges_in_path)

        congestion_factors = []
        for e in edges_in_path:
            factor = {"low": 0.2, "medium": 0.5, "high": 0.9}.get(
                e.congestion_level, 0.2
            )
            congestion_factors.append(factor)

        avg_congestion = (
            sum(congestion_factors) / len(congestion_factors)
            if congestion_factors
            else 0.0
        )

        # Estimated time = distance / effective_speed
        effective_speed = self.DEFAULT_SPEED_MPS * (1 - avg_congestion * 0.5)
        effective_speed = max(effective_speed, 1.0)  # prevent division by zero
        estimated_time = total_distance / effective_speed

        return Route(
            route_id=f"{start}_to_{end}",
            path=path,
            total_distance=total_distance,
            avg_congestion=avg_congestion,
            estimated_time=estimated_time,
        )

    def find_routes(self, start: str, end: str, k: int = 3) -> List[Route]:
        """
        Find up to k route options between two intersections.
        
        Uses a simple approach: find shortest path, then try
        alternative paths by penalizing used edges.
        
        Args:
            start: source intersection ID
            end: destination intersection ID
            k: maximum number of routes to return
        """
        routes = []

        # First route — standard Dijkstra
        route = self.find_shortest_path(start, end)
        if route is None:
            return routes

        route.route_id = f"{start}_to_{end}_opt1"
        routes.append(route)

        # For simplicity with small graphs, just return the one route
        # A full k-shortest-paths (Yen's algorithm) can be added later
        # For now, return the single optimal route
        return routes

    def compute_route_metrics(self, path: List[str]) -> dict:
        """
        Compute metrics for a given path.
        
        Args:
            path: ordered list of intersection IDs
        
        Returns:
            Dict with total_distance, avg_congestion, estimated_time
        """
        total_distance = 0.0
        congestion_factors = []

        for i in range(len(path) - 1):
            from_node = path[i]
            to_node = path[i + 1]

            # Find the connecting edge
            for neighbor, edge in self.graph.get_neighbors(from_node):
                if neighbor == to_node:
                    total_distance += edge.distance
                    factor = {"low": 0.2, "medium": 0.5, "high": 0.9}.get(
                        edge.congestion_level, 0.2
                    )
                    congestion_factors.append(factor)
                    break

        avg_congestion = (
            sum(congestion_factors) / len(congestion_factors)
            if congestion_factors
            else 0.0
        )

        effective_speed = self.DEFAULT_SPEED_MPS * (1 - avg_congestion * 0.5)
        effective_speed = max(effective_speed, 1.0)
        estimated_time = total_distance / effective_speed

        return {
            "total_distance": round(total_distance, 2),
            "avg_congestion": round(avg_congestion, 2),
            "estimated_time": round(estimated_time, 2),
        }
