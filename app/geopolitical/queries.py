"""Geopolitical news category definitions and GDELT DOC 2.0 query builder."""
from typing import Dict, List, Optional
from app.schemas.geopolitical import GeopoliticalCategory, CriticalMineral


# Core keyword clauses for the 4 critical minerals
MINERAL_QUERIES: Dict[CriticalMineral, str] = {
    CriticalMineral.COBALT: "cobalt",
    CriticalMineral.LITHIUM: "lithium",
    CriticalMineral.NICKEL: "nickel",
    CriticalMineral.NATURAL_GRAPHITE: '(graphite OR "natural graphite")',
}

ALL_MINERALS_CLAUSE = '(cobalt OR lithium OR nickel OR graphite OR "critical minerals")'


# Configurable search queries for the 9 geopolitical risk categories
CATEGORY_QUERIES: Dict[GeopoliticalCategory, str] = {
    GeopoliticalCategory.ARMED_CONFLICT: (
        '("armed conflict" OR war OR military OR combat OR insurgency OR rebellion OR fighting)'
    ),
    GeopoliticalCategory.POLITICAL_INSTABILITY: (
        '("political instability" OR coup OR unrest OR "civil unrest" OR "political crisis" OR regime OR protest)'
    ),
    GeopoliticalCategory.MINING_STRIKES: (
        '(strike OR "labor strike" OR "workers strike" OR walkout OR "work stoppage") (mine OR mining OR miners)'
    ),
    GeopoliticalCategory.PRODUCTION_DISRUPTIONS: (
        '("production disruption" OR "mine shutdown" OR "output halt" OR "smelter closure" OR "supply outage" OR "production halted")'
    ),
    GeopoliticalCategory.TRADE_RESTRICTIONS: (
        '("export ban" OR "trade restriction" OR "export restrictions" OR "export controls" OR tariff OR quota OR "trade ban")'
    ),
    GeopoliticalCategory.PORT_CLOSURES: (
        '("port closure" OR "port closed" OR "dock strike" OR "shipping terminal" OR "berth closed" OR "harbor closure")'
    ),
    GeopoliticalCategory.TRANSPORT_DISRUPTIONS: (
        '("transport disruption" OR "rail disruption" OR "logistics bottleneck" OR "freight disruption" OR blockade OR "freight delay")'
    ),
    GeopoliticalCategory.SANCTIONS_ANNOUNCEMENTS: (
        '(sanctions OR sanctioned OR "trade embargo" OR blacklist OR "asset freeze" OR "export restriction")'
    ),
    GeopoliticalCategory.NATURAL_DISASTERS: (
        '(earthquake OR flood OR cyclone OR hurricane OR landslide OR drought OR typhoon OR tsunami) (mine OR mining OR smelter OR processing)'
    ),
}

CATEGORY_METADATA: Dict[GeopoliticalCategory, Dict[str, str]] = {
    GeopoliticalCategory.ARMED_CONFLICT: {
        "name": "Armed Conflicts & Wars",
        "description": "Armed clashes, warfare, insurgencies, or military operations disrupting mineral regions.",
    },
    GeopoliticalCategory.POLITICAL_INSTABILITY: {
        "name": "Political Instability",
        "description": "Coups, widespread civil unrest, regime shifts, or nationalizations threatening mining concessions.",
    },
    GeopoliticalCategory.MINING_STRIKES: {
        "name": "Mining Strikes",
        "description": "Labor actions, walkouts, or union strikes halting mineral extraction and refining.",
    },
    GeopoliticalCategory.PRODUCTION_DISRUPTIONS: {
        "name": "Mineral Production Disruptions",
        "description": "Operational shutdowns, power outages, smelter halts, or supply constraints.",
    },
    GeopoliticalCategory.TRADE_RESTRICTIONS: {
        "name": "Export Bans & Trade Restrictions",
        "description": "Export controls, resource nationalism, tariffs, or raw mineral export bans.",
    },
    GeopoliticalCategory.PORT_CLOSURES: {
        "name": "Port Closures",
        "description": "Seaport shutdowns, berth closures, or dock strikes disrupting maritime mineral shipments.",
    },
    GeopoliticalCategory.TRANSPORT_DISRUPTIONS: {
        "name": "Transportation Disruptions",
        "description": "Rail delays, logistics blockades, freight halts, or critical corridor bottlenecks.",
    },
    GeopoliticalCategory.SANCTIONS_ANNOUNCEMENTS: {
        "name": "Sanctions Announcements",
        "description": "International sanctions, SDN designations, or embargoes targeting mineral supply entities.",
    },
    GeopoliticalCategory.NATURAL_DISASTERS: {
        "name": "Natural Disasters",
        "description": "Earthquakes, floods, cyclones, or landslides impacting mining infrastructure or transport routes.",
    },
}


def convert_hours_to_timespan(hours: int) -> str:
    """
    Converts lookback hours to standard GDELT DOC 2.0 timespan shorthand.
    Examples:
        24  -> '24h'
        48  -> '2d'
        168 -> '7d'
    """
    if hours <= 0:
        return "24h"
    if hours < 24:
        return f"{hours}h"
    if hours % 24 == 0:
        days = hours // 24
        if days % 7 == 0 and days >= 7:
            weeks = days // 7
            return f"{weeks}w"
        return f"{days}d"
    return f"{hours}h"


def build_category_query(
    category: GeopoliticalCategory,
    mineral: Optional[CriticalMineral] = None,
    extra_terms: Optional[str] = None,
) -> str:
    """
    Constructs a precise, targeted GDELT DOC 2.0 query combining mineral keywords
    with category-specific disruption indicators.
    """
    cat_clause = CATEGORY_QUERIES.get(category, "")
    if not cat_clause:
        raise ValueError(f"Unknown geopolitical category: {category}")

    if mineral:
        min_clause = MINERAL_QUERIES.get(mineral, mineral.value)
    else:
        min_clause = ALL_MINERALS_CLAUSE

    query = f"{min_clause} {cat_clause}"
    if extra_terms and extra_terms.strip():
        query = f"{query} {extra_terms.strip()}"

    return query


def build_critical_minerals_disruption_query(
    mineral: Optional[CriticalMineral] = None,
) -> str:
    """
    Builds a composite query covering any major supply chain disruption across
    targeted critical minerals.
    """
    if mineral:
        min_clause = MINERAL_QUERIES.get(mineral, mineral.value)
    else:
        min_clause = ALL_MINERALS_CLAUSE

    disruption_terms = (
        '("supply disruption" OR "mining strike" OR "export ban" OR "mine shutdown" OR sanctions OR "port closure" OR war OR unrest OR "maritime attack" OR flood OR earthquake OR "border closure" OR "shipping disruption")'
    )
    if not mineral:
        min_clause = '(cobalt OR lithium OR nickel OR graphite OR "Red Sea" OR "Bab el-Mandeb" OR "Suez Canal")'
    return f"{min_clause} {disruption_terms}"
