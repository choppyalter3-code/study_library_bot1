from dataclasses import dataclass


@dataclass
class Category:
    category_id: int
    name: str
    icon: str
    sort_order: int


@dataclass
class Material:
    material_id: int
    category_id: int
    title: str
    description: str
    link: str
    tags: str
    file_id: str
    created_at_iso: str


@dataclass
class MaterialView:
    material: Material
    viewed_at_iso: str


@dataclass
class SearchLog:
    query: str
    results_count: int
    created_at_iso: str


@dataclass
class PopularMaterial:
    material: Material
    views_count: int


@dataclass
class SearchQueryStat:
    query: str
    search_count: int
