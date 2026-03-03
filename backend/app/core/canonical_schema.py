"""Canonical columns: AI maps source Excel columns to these."""
CANONICAL_COLUMNS = ["SKU", "Name", "Description", "Brand Name", "UPC", "Price"]
OPTIONAL_CANONICAL = ["MPN", "Weight", "Height", "Width", "Length", "Color", "Product URL"]
ALL_CANONICAL = CANONICAL_COLUMNS + OPTIONAL_CANONICAL
