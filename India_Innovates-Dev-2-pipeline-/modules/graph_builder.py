"""
Phase 9 — City-Level Graph Construction
Builds a graph representation of the city: nodes=intersections, edges=roads.
Used for routing and multi-intersection coordination.
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
import heapq


@dataclass
class GraphNode:
    """An intersection node in the city graph."""
    node_id: str
    name: str
    latitude: float
    longitude: float
    state: Optional[dict] = None   # IntersectionState dict

    def to_dict(self) -> dict:
        d = {
            "node_id": self.node_id,
            "name": self.name,
            "latitude": self.latitude,
            "longitude": self.longitude,
        }
        if self.state:
            d["state"] = self.state
        return d


@dataclass
class GraphEdge:
    """A road edge connecting two intersections."""
    edge_id: str
    from_node: str
    to_node: str
    distance: float
    vehicle_count: int = 0
    avg_speed: float = 0.0
    congestion_level: str = "low"  # low / medium / high

    def to_dict(self) -> dict:
        return {
            "edge_id": self.edge_id,
            "from": self.from_node,
            "to": self.to_node,
            "distance": self.distance,
            "vehicle_count": self.vehicle_count,
            "avg_speed": round(self.avg_speed, 2),
            "congestion_level": self.congestion_level,
        }

    @property
    def weight(self) -> float:
        """Edge weight for routing — lower is better."""
        # Factor in both distance and congestion
        congestion_factor = {
            "low": 1.0,
            "medium": 1.5,
            "high": 3.0,
        }.get(self.congestion_level, 1.0)
        return self.distance * congestion_factor


class CityGraph:
    """
    Graph representation of the city road network.
    
    Supports:
    - Node/edge management
    - Adjacency list traversal
    - Traffic metric attachment to edges
    - Input for routing (Phase 11)
    """

    def __init__(self):
        self.nodes: Dict[str, GraphNode] = {}
        self.edges: List[GraphEdge] = []
        self.adjacency: Dict[str, List[Tuple[str, GraphEdge]]] = {}

    def add_node(self, node_id: str, name: str, lat: float, lon: float):
        """Add an intersection node."""
        self.nodes[node_id] = GraphNode(
            node_id=node_id, name=name, latitude=lat, longitude=lon
        )
        if node_id not in self.adjacency:
            self.adjacency[node_id] = []

    def add_edge(self, edge_id: str, from_node: str, to_node: str, distance: float):
        """Add a road edge (bidirectional)."""
        edge = GraphEdge(
            edge_id=edge_id,
            from_node=from_node,
            to_node=to_node,
            distance=distance,
        )
        self.edges.append(edge)

        # Bidirectional
        if from_node not in self.adjacency:
            self.adjacency[from_node] = []
        if to_node not in self.adjacency:
            self.adjacency[to_node] = []

        self.adjacency[from_node].append((to_node, edge))
        self.adjacency[to_node].append((from_node, edge))

    def update_edge_metrics(self, edge_id: str, vehicle_count: int, avg_speed: float):
        """Update traffic metrics on an edge."""
        for edge in self.edges:
            if edge.edge_id == edge_id:
                edge.vehicle_count = vehicle_count
                edge.avg_speed = avg_speed

                # Determine congestion level
                if vehicle_count > 15:
                    edge.congestion_level = "high"
                elif vehicle_count > 8:
                    edge.congestion_level = "medium"
                else:
                    edge.congestion_level = "low"
                break

    def attach_intersection_state(self, node_id: str, state_dict: dict):
        """Attach intersection state data to a node."""
        if node_id in self.nodes:
            self.nodes[node_id].state = state_dict

    def get_neighbors(self, node_id: str) -> List[Tuple[str, GraphEdge]]:
        """Get adjacent nodes and their connecting edges."""
        return self.adjacency.get(node_id, [])

    def to_dict(self) -> dict:
        """Serialize the graph."""
        return {
            "nodes": [n.to_dict() for n in self.nodes.values()],
            "edges": [e.to_dict() for e in self.edges],
        }


class GraphBuilder:
    """Builds a CityGraph from intersection configuration."""

    @staticmethod
    def from_config(config: dict) -> CityGraph:
        """
        Build city graph from intersection_config.json.
        
        Args:
            config: parsed intersection_config.json
        """
        graph = CityGraph()

        # Add all intersection nodes
        all_geo = config.get("all_intersections_geo", {})
        for int_id, info in all_geo.items():
            graph.add_node(
                node_id=int_id,
                name=info.get("name", int_id),
                lat=info.get("latitude", 0),
                lon=info.get("longitude", 0),
            )

        # Also add from the intersections array if not in all_geo
        for intersection in config.get("intersections", []):
            int_id = intersection["intersection_id"]
            if int_id not in graph.nodes:
                graph.add_node(
                    node_id=int_id,
                    name=intersection.get("name", int_id),
                    lat=intersection.get("latitude", 0),
                    lon=intersection.get("longitude", 0),
                )

        # Add road edges
        for road in config.get("roads", []):
            graph.add_edge(
                edge_id=road["road_id"],
                from_node=road["from_intersection"],
                to_node=road["to_intersection"],
                distance=road["distance"],
            )

        return graph
