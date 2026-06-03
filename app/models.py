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
