"""Artifact types for job outputs."""

from enum import StrEnum


class ArtifactType(StrEnum):
    """Artifact types for job outputs."""

    TEXT = "text"
    JSON = "json"
    PNG = "image/png"
    JPEG = "image/jpeg"
    WEBP = "image/webp"
    GIF = "image/gif"
    SVG = "image/svg"
    PDF = "file/pdf"
    CSV = "file/csv"
    XML = "file/xml"
    HTML = "file/html"
    BINARY = "file/binary"
