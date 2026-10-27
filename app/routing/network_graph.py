"""
Transport Network Graph and Candidate Pathfinding Engine using NetworkX.
Maintains multimodal mineral transport network and dynamically reroutes around disruptions.
"""
from typing import Dict, Any, List, Optional, Tuple
import networkx as nx

# Global network graph of mineral logistics hubs and transit edges
DEFAULT_NETWORK_EDGES = [
    # Southern Africa Cobalt Corridors
    ("kolwezi_hub", "lubumbashi_hub", {"distance_km": 300, "mode": "ROAD", "hub_name": "Kolwezi-Lubumbashi Highway"}),
    ("lubumbashi_hub", "kasumbalesa_border", {"distance_km": 100, "mode": "ROAD", "hub_name": "Kasumbalesa Border"}),
    ("kasumbalesa_border", "ndola_hub", {"distance_km": 110, "mode": "ROAD", "hub_name": "Zambia Northern Corridor"}),
    ("ndola_hub", "lusaka_hub", {"distance_km": 310, "mode": "ROAD", "hub_name": "Great North Road"}),
    ("lusaka_hub", "durban_port", {"distance_km": 1800, "mode": "ROAD_RAIL", "hub_name": "Port of Durban Corridor"}),
    # Alternative Southern Africa Corridors
    ("lusaka_hub", "walvis_bay_port", {"distance_km": 1750, "mode": "ROAD", "hub_name": "Trans-Caprivi Corridor (Walvis Bay)"}),
    ("ndola_hub", "dar_es_salaam_port", {"distance_km": 1600, "mode": "RAIL_ROAD", "hub_name": "TAZARA Corridor (Dar es Salaam)"}),

    # Chile Lithium Corridors
    ("atacama_salars", "antofagasta_port", {"distance_km": 310, "mode": "ROAD", "hub_name": "Antofagasta Lithium Route"}),
    ("atacama_salars", "mejillones_port", {"distance_km": 340, "mode": "ROAD", "hub_name": "Mejillones Alternative Corridor"}),
    ("atacama_salars", "iquique_port", {"distance_km": 480, "mode": "ROAD", "hub_name": "Iquique Northern Backup Port"}),

    # Indonesia Nickel Corridors
    ("morowali_imip", "bahodopi_port", {"distance_km": 15, "mode": "CONVEYOR_ROAD", "hub_name": "Bahodopi Mineral Pier"}),
    ("bahodopi_port", "makassar_strait", {"distance_km": 600, "mode": "MARITIME", "hub_name": "Makassar Shipping Lane"}),
    ("makassar_strait", "ningbo_port", {"distance_km": 3800, "mode": "MARITIME", "hub_name": "East China Sea Shipping Lane"}),
    # Alternative Indonesia Port
    ("morowali_imip", "kendari_port", {"distance_km": 280, "mode": "COASTAL_BARGE", "hub_name": "Kendari Backup Port"}),
    ("kendari_port", "makassar_strait", {"distance_km": 500, "mode": "MARITIME", "hub_name": "Flores-Makassar Lane"}),

    # Mozambique Graphite Corridors
    ("balama_mine", "nacala_port", {"distance_km": 480, "mode": "ROAD", "hub_name": "Nacala Graphite Highway"}),
    ("balama_mine", "pemba_port", {"distance_km": 260, "mode": "ROAD", "hub_name": "Pemba Regional Port Alternative"}),

    # Red Sea vs Cape of Good Hope Maritime Corridors
    ("gulf_of_aden", "bab_el_mandeb", {"distance_km": 180, "mode": "MARITIME", "hub_name": "Bab el-Mandeb Channel"}),
    ("bab_el_mandeb", "suez_canal", {"distance_km": 2100, "mode": "MARITIME", "hub_name": "Red Sea Transit Lane"}),
    ("suez_canal", "europe_med_hub", {"distance_km": 2500, "mode": "MARITIME", "hub_name": "Eastern Mediterranean Route"}),
    # Alternative Cape of Good Hope Route
    ("gulf_of_aden", "cape_of_good_hope", {"distance_km": 7200, "mode": "MARITIME", "hub_name": "Cape Route Southbound"}),
    ("cape_of_good_hope", "europe_med_hub", {"distance_km": 8800, "mode": "MARITIME", "hub_name": "Atlantic Route Northbound"}),
]

ROUTE_GRAPH_TERMINALS: Dict[str, Tuple[str, str]] = {
    "route_cod_durban_cobalt": ("kolwezi_hub", "durban_port"),
    "route_chl_antofagasta_lithium": ("atacama_salars", "antofagasta_port"),
    "route_idn_morowali_nickel": ("morowali_imip", "ningbo_port"),
    "route_moz_nacala_graphite": ("balama_mine", "nacala_port"),
    "route_red_sea_suez_minerals": ("gulf_of_aden", "europe_med_hub"),
}


class TransportNetworkGraph:
    """
    Graph-based candidate alternative routing engine using NetworkX.
    Evaluates shortest alternative corridors avoiding confirmed closures.
    """

    def __init__(self):
        self.graph = nx.Graph()
        self._build_default_graph()

    def _build_default_graph(self):
        for u, v, data in DEFAULT_NETWORK_EDGES:
            self.graph.add_edge(u, v, **data, effective_weight=data["distance_km"])

    def find_candidate_alternative(
        self,
        route_id: str,
        blocked_hubs: Optional[List[str]] = None,
        penalized_hubs: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Calculates alternative candidate path avoiding blocked nodes and penalizing at-risk nodes.
        Returns alternative route details or None if no path exists.
        """
        if route_id not in ROUTE_GRAPH_TERMINALS:
            return None

        import re
        normalize = lambda value: re.sub(r"[^a-z0-9]", "", value.lower().replace("port of ", "").replace(" strait", "").replace(" channel", ""))
        origin, target = ROUTE_GRAPH_TERMINALS[route_id]
        g = self.graph.copy()
        def hit(value, node):
            a, b = normalize(value), normalize(node.replace("_port", "").replace("_hub", ""))
            return bool(a and b and (a in b or b in a))
        for node in list(g):
            if any(hit(h,node) for h in (blocked_hubs or [])): g.remove_node(node)
        if origin not in g or target not in g: return None
        for u,v,d in g.edges(data=True):
            d["effective_weight"] = d["distance_km"] * (3 if any(hit(h,u) or hit(h,v) for h in (penalized_hubs or [])) else 1)
        baseline = nx.shortest_path(self.graph, origin, target, weight="distance_km")
        try:
            paths = nx.shortest_simple_paths(g, origin, target, weight="effective_weight")
            path = next((p for p in paths if p != baseline), None)
        except nx.NetworkXNoPath:
            return None
        if path is None: return None
        distance = sum(g[a][b]["distance_km"] for a,b in zip(path,path[1:]))
        cost = sum(g[a][b]["effective_weight"] for a,b in zip(path,path[1:]))
        return {
            "alternative_route_id": f"alt_{route_id}",
            "alternative_route_name": "Candidate via " + " → ".join(path),
            "waypoints": path, "estimated_distance_km": distance,
            "risk_weighted_cost": cost,
            "designation": "CANDIDATE ALTERNATIVE — NOT CARRIER VERIFIED",
            "justification": "Different stored graph path to the same destination; closed nodes excluded; risk penalty multiplier 3.",
            "disclaimer": "Illustrative graph distances; no carrier, ETA, cost or legal clearance evidence.",
        }
