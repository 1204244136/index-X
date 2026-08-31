#!/usr/bin/env python3
"""Compare raster images in paired Chinese/Japanese EPUB cache books.

The report is deliberately conservative: exact byte matches and decoded pixel
matches are separated from perceptual candidates.  A perceptual candidate can
be an illustration with translated or replaced lettering, but it always needs
human visual confirmation.

Examples::

    python tools/compare_epub_images.py
    python tools/compare_epub_images.py --pattern "*S1_01*"
    python tools/compare_epub_images.py --cache .cache/epub-work --output .cache/epub-work/image-comparison
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import re
import sys
import urllib.parse
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from alignment_rules import NON_PAIR_WORK_IDS, pairing_header_of
from epub_ids import book_id, japanese_book_id

try:
    from PIL import Image, ImageFilter, ImageOps, UnidentifiedImageError
except ImportError as exc:  # pragma: no cover - exercised only on missing dependency
    raise SystemExit("需要 Pillow：请先安装 `python -m pip install Pillow`") from exc

try:
    import imagehash
except ImportError:  # Optional: the Pillow metrics below remain usable.
    imagehash = None


IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".svg"
}
XHTML_EXTENSIONS = {".xhtml", ".html"}

def image_files(book: Path) -> list[Path]:
    return sorted(
        (path for path in book.rglob("*")
         if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS),
        key=lambda path: path.relative_to(book).as_posix().casefold(),
    )


@dataclass
class Asset:
    path: Path
    relative: str
    name: str
    size: int
    sha256: str
    references: list[str] = field(default_factory=list)
    pages: list[str] = field(default_factory=list)
    # Stable page/slot locations let the name-rule layer handle translated
    # lettering even when the raster pixels differ too much for a match.
    locations: list[str] = field(default_factory=list)
    width: int | None = None
    height: int | None = None
    layout: str | None = None
    decode_error: str | None = None
    _feature: "Feature | None" = field(default=None, repr=False)

    def json(self) -> dict:
        return {
            "path": self.relative,
            "name": self.name,
            "bytes": self.size,
            "sha256": self.sha256,
            "width": self.width,
            "height": self.height,
            "layout": self.layout,
            "referenced_by": self.references,
            "pages": self.pages,
            "locations": self.locations,
            "decode_error": self.decode_error,
        }


@dataclass(frozen=True)
class Feature:
    # Values are tuples to keep features cheap to retain for all books.
    ratio: float
    pixels: tuple[int, ...]
    blurred: tuple[int, ...]
    edges: tuple[int, ...]
    dhash: int
    histogram: tuple[float, ...]
    luma_std: float
    edge_density: float
    phash: str | None
    whash: str | None
    colorhash: str | None


@dataclass
class Match:
    chinese: Asset
    japanese: Asset
    kind: str
    score: float | None = None
    pixel_mae: float | None = None
    blurred_mae: float | None = None
    edge_mae: float | None = None
    histogram: float | None = None
    dhash_distance: int | None = None
    phash_distance: int | None = None
    whash_distance: int | None = None
    colorhash_distance: int | None = None
    reason: str = ""
    japanese_parts: list[Asset] = field(default_factory=list)

    def json(self) -> dict:
        return {
            "chinese": self.chinese.json(),
            "japanese": self.japanese.json(),
            "classification": self.kind,
            "score": round(self.score, 5) if self.score is not None else None,
            "pixel_mae": round(self.pixel_mae, 5) if self.pixel_mae is not None else None,
            "blurred_mae": round(self.blurred_mae, 5) if self.blurred_mae is not None else None,
            "edge_mae": round(self.edge_mae, 5) if self.edge_mae is not None else None,
            "histogram_intersection": round(self.histogram, 5) if self.histogram is not None else None,
            "dhash_distance": self.dhash_distance,
            "phash_distance": self.phash_distance,
            "whash_distance": self.whash_distance,
            "colorhash_distance": self.colorhash_distance,
            "reason": self.reason,
            "japanese_parts": [asset.json() for asset in self.japanese_parts],
        }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _letterboxed(image: Image.Image, size: int = 32) -> Image.Image:
    image = ImageOps.exif_transpose(image).convert("RGB")
    # Preserve aspect ratio.  A neutral background avoids inventing edge
    # structure when a Japanese and Chinese scan use different dimensions.
    thumb = image.copy()
    thumb.thumbnail((size, size), Image.Resampling.LANCZOS)
    background = Image.new("RGB", (size, size), (128, 128, 128))
    background.paste(thumb, ((size - thumb.width) // 2, (size - thumb.height) // 2))
    return background


def _values(image: Image.Image) -> tuple[int, ...]:
    return tuple(image.convert("L").getdata())


def _layout_from_ratio(ratio: float) -> str:
    """Classify body art by its stable portrait/spread aspect ratio."""
    if ratio >= 1.10:
        return "double_page_candidate"
    if ratio <= 0.90:
        return "single_page_candidate"
    return "ambiguous_aspect_ratio"


def _dhash(image: Image.Image) -> int:
    small = image.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    pixels = list(small.getdata())
    value = 0
    for row in range(8):
        for col in range(8):
            value = (value << 1) | int(pixels[row * 9 + col] > pixels[row * 9 + col + 1])
    return value


def _edges(image: Image.Image) -> tuple[int, ...]:
    pixels = list(image.convert("L").getdata())
    width, height = image.size
    result: list[int] = []
    for y in range(height):
        for x in range(width):
            current = pixels[y * width + x]
            right = pixels[y * width + min(x + 1, width - 1)]
            below = pixels[min(y + 1, height - 1) * width + x]
            result.append(min(255, abs(current - right) + abs(current - below)))
    return tuple(result)


def _histogram(image: Image.Image) -> tuple[float, ...]:
    result: list[float] = []
    # Coarse RGB histograms are tolerant of JPEG quality and translated glyphs.
    for channel in range(3):
        values = list(image.getchannel(channel).getdata())
        bins = [0] * 16
        for value in values:
            bins[min(15, value * 16 // 256)] += 1
        total = len(values) or 1
        result.extend(count / total for count in bins)
    return tuple(result)


def feature(asset: Asset) -> Feature | None:
    if asset._feature is not None:
        return asset._feature
    try:
        with Image.open(asset.path) as source:
            asset.width, asset.height = source.size
            boxed = _letterboxed(source)
            gray = boxed.convert("L")
            blurred = gray.filter(ImageFilter.GaussianBlur(radius=2))
            gray_values = _values(gray)
            mean_luma = sum(gray_values) / (len(gray_values) or 1)
            luma_std = math.sqrt(
                sum((value - mean_luma) ** 2 for value in gray_values)
                / (len(gray_values) or 1)
            )
            edge_values = _edges(gray)
            edge_density = sum(value > 20 for value in edge_values) / (len(edge_values) or 1)
            phash = whash = colorhash = None
            if imagehash is not None:
                # ImageHash's established implementations add robustness to
                # resampling and JPEG quality changes. Keep hash_size=8 so
                # distances are 64-bit and easy to interpret in reports.
                phash = str(imagehash.phash(boxed, hash_size=8))
                whash = str(imagehash.whash(boxed, hash_size=8))
                colorhash = str(imagehash.colorhash(boxed))
            asset._feature = Feature(
                ratio=asset.width / asset.height if asset.height else 0,
                pixels=gray_values,
                blurred=_values(blurred),
                edges=edge_values,
                dhash=_dhash(gray),
                histogram=_histogram(boxed),
                luma_std=luma_std,
                edge_density=edge_density,
                phash=phash,
                whash=whash,
                colorhash=colorhash,
            )
            asset.layout = _layout_from_ratio(asset._feature.ratio)
            return asset._feature
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        asset.decode_error = str(exc)
        return None


def _mae(first: Iterable[int], second: Iterable[int]) -> float:
    values = list(zip(first, second))
    if not values:
        return 1.0
    return sum(abs(a - b) for a, b in values) / len(values) / 255.0


def _histogram_intersection(first: tuple[float, ...], second: tuple[float, ...]) -> float:
    return sum(min(a, b) for a, b in zip(first, second)) / 3.0


def _hamming(first: int, second: int) -> int:
    return (first ^ second).bit_count()


def _library_hash_distance(first: str | None, second: str | None) -> int | None:
    if not first or not second:
        return None
    try:
        return (int(first, 16) ^ int(second, 16)).bit_count()
    except ValueError:
        return None


def page_role(name: str) -> str:
    """Return a conservative semantic role for an XHTML page filename."""
    stem = Path(name).stem.casefold()
    if "bookwalker" in stem:
        return "bookwalker"
    if "allcover" in stem:
        return "allcover"
    if "back_cover" in stem or "back-cover" in stem or "hyou4" in stem:
        return "back_cover"
    if "cover" in stem or "hyoushi" in stem:
        return "cover"
    if "contents" in stem or re.search(r"(?:^|[-_])toc(?:[-_]|$)", stem):
        return "contents"
    if "illustration" in stem or "kuchie" in stem:
        return "illustrations"
    return "body"


def image_name_family(name: str) -> tuple[str, int | None]:
    """Map a Chinese/Japanese asset filename to a cautious semantic family.

    The numeric value is meaningful only for illustration assets.  Japanese
    body filenames contain source page numbers, not the Chinese pN sequence.
    """
    stem = Path(name).stem.casefold()
    # Strip the stable work/volume prefix while preserving the semantic
    # suffix.  This covers S1/S2/S3/S4, S5 independent works, and S6 dates.
    stem = re.sub(r"^s\d+_(?:\d+(?:\.\d+){2}|\d+(?:_\d+)?)[-_]", "", stem)
    if stem in {"cover", "hyoushi", "hyoushi-1", "hyoushi-2"}:
        return "cover", None
    if stem in {"back_cover", "back-cover", "hyou4", "hyoushi-4"}:
        return "back_cover", None
    if stem in {"contents", "toc", "toc-001", "toc-002"} or stem.startswith("toc-"):
        return "contents", None
    if stem in {"deputy_cover", "deputy-cover", "kuchie-001"}:
        return "deputy_cover", 1
    match = re.fullmatch(r"illustrations?(\d+)", stem)
    if match:
        return "illustration", int(match.group(1))
    match = re.fullmatch(r"kuchie-(\d+)", stem)
    if match:
        number = int(match.group(1))
        return "illustration", number - 1 if number > 1 else 1
    if body_number_key(name) is not None:
        return "body", None
    return "other", None


def body_number_key(name: str) -> str | None:
    """Return a normalized illustration number/range from a body filename.

    The Chinese side may use ``S2_09-p016-p017`` while the Japanese side uses
    ``p016-p017``; the newer files use ``i-016-017``.  The older S1 package
    names (``p000-00-16-1``) are kept in a separate namespace because their
    final ``-1`` is a source-image suffix, not a page range.
    """
    stem = Path(name).stem.casefold()
    stem = re.sub(r"^s\d+_(?:\d+(?:\.\d+){2}|\d+(?:_\d+)?)[-_]", "", stem)
    match = re.fullmatch(r"(?:i|p)-?(\d+)(?:-(?:i|p)?(\d+))?", stem)
    if match:
        first, second = int(match.group(1)), match.group(2)
        return str(first) if second is None else f"{first}-{int(second)}"
    match = re.fullmatch(r"p\d+-\d+-(\d+)-(\d+)", stem)
    if match:
        return f"legacy:{int(match.group(1))}-{int(match.group(2))}"
    return None


def body_number_parts(name: str) -> tuple[int, ...] | None:
    """Return numeric parts for a normalized double-page filename."""
    key = body_number_key(name)
    if key is None or key.startswith("legacy:") or "-" not in key:
        return None
    try:
        parts = tuple(int(part) for part in key.split("-"))
    except ValueError:
        return None
    return parts if len(parts) == 2 else None


def _strong_visual_match(first: Asset, second: Asset) -> bool:
    """Require clear visual support for ambiguous illustration name rules."""
    metrics = compare(first, second)
    if metrics is None:
        return False
    pixel_mae, blurred_mae, dhash_distance = metrics[1], metrics[2], metrics[4]
    phash_distance, whash_distance = metrics[6], metrics[7]
    return (
        pixel_mae <= 0.025
        and blurred_mae <= 0.02
        and (
            dhash_distance <= 4
            or (
                phash_distance is not None
                and phash_distance <= 6
                and (whash_distance is None or whash_distance <= 8)
            )
        )
    )


def _uses_s1_illustration_sequence(name: str) -> bool:
    """Return whether the observed S1 package naming sequence applies."""
    stem = Path(name).stem.casefold()
    return bool(re.match(r"^s1_\d+(?:-|_)", stem))


def name_rule_match(chinese: Asset, japanese: Asset) -> tuple[bool, str]:
    """Check a name-family match at the same page/slot location."""
    cn_family, cn_number = image_name_family(chinese.name)
    jp_family, jp_number = image_name_family(japanese.name)
    if cn_family == "other" or jp_family == "other" or cn_family != jp_family:
        return False, ""
    if cn_family == "body":
        cn_key, jp_key = body_number_key(chinese.name), body_number_key(japanese.name)
        if cn_key is not None and cn_key == jp_key:
            if chinese.layout and japanese.layout and chinese.layout != japanese.layout:
                return False, ""
            return True, "正文图片编号相同 + 单双页尺寸类别相同"
        # Once both sides use the normalized i-NNN/pNNN naming scheme, a
        # shared XHTML slot is not reliable: the Japanese XHTML may contain
        # an extra image and shift every later slot.  Keep slot fallback only
        # for the historical pN <-> p000-00-XX-1 packages.
        if (
            cn_key is not None
            and jp_key is not None
            and not (cn_key.startswith("legacy:") or jp_key.startswith("legacy:"))
        ):
            return False, ""
    if not set(chinese.locations).intersection(japanese.locations):
        return False, ""
    if cn_family == "illustration" and cn_number != jp_number:
        # Some source books swap illustration files; visual matching remains
        # the authority for those cases.
        return False, ""
    if (
        cn_family in {"deputy_cover", "illustration"}
        and not _uses_s1_illustration_sequence(chinese.name)
        and not _strong_visual_match(chinese, japanese)
    ):
        # kuchie numbering is not globally stable: some Japanese books omit
        # the first kuchie image or use a different package-page role.
        return False, ""
    labels = {
        "cover": "Cover/cover",
        "back_cover": "Back_cover/hyou4",
        "contents": "Contents/toc",
        "deputy_cover": "Deputy_cover/kuchie-001",
        "illustration": "IllustrationsN/kuchie-(N+1)",
        "body": "正文图片编号/图片族 + 同一表头/槽位",
    }
    return True, labels[cn_family]


def body_layout_mismatches(cn_assets: list[Asset], jp_assets: list[Asset]) -> list[tuple[Asset, Asset]]:
    """Find equal illustration numbers whose aspect-ratio classes disagree."""
    cn_by_key: dict[str, list[Asset]] = defaultdict(list)
    jp_by_key: dict[str, list[Asset]] = defaultdict(list)
    for asset in cn_assets:
        key = body_number_key(asset.name)
        if key is not None and asset.layout:
            cn_by_key[key].append(asset)
    for asset in jp_assets:
        key = body_number_key(asset.name)
        if key is not None and asset.layout:
            jp_by_key[key].append(asset)
    result: list[tuple[Asset, Asset]] = []
    for key in sorted(set(cn_by_key).intersection(jp_by_key)):
        for chinese in cn_by_key[key]:
            for japanese in jp_by_key[key]:
                if chinese.layout != japanese.layout:
                    result.append((chinese, japanese))
    return result


def compare(first: Asset, second: Asset) -> tuple[float, float, float, float, int, float, int | None, int | None, int | None] | None:
    f1, f2 = feature(first), feature(second)
    if f1 is None or f2 is None:
        return None
    if f1.ratio == 0 or f2.ratio == 0:
        return None
    # Large white/black margins make perceptual hashes overconfident for
    # unrelated logos and placeholder pages. Exact SHA-256 matches are handled
    # before this function, so skipping low-information visual candidates is
    # deliberately conservative.
    if min(f1.luma_std, f2.luma_std) < 25.0:
        return None
    if f1.edge_density < 0.19 and f2.edge_density < 0.19:
        return None
    ratio_delta = abs(math.log(f1.ratio / f2.ratio))
    if ratio_delta > 0.18:  # approximately 20% aspect-ratio difference
        return None
    pixel_mae = _mae(f1.pixels, f2.pixels)
    blurred_mae = _mae(f1.blurred, f2.blurred)
    edge_mae = _mae(f1.edges, f2.edges)
    histogram = _histogram_intersection(f1.histogram, f2.histogram)
    dhash_distance = _hamming(f1.dhash, f2.dhash)
    phash_distance = _library_hash_distance(f1.phash, f2.phash)
    whash_distance = _library_hash_distance(f1.whash, f2.whash)
    colorhash_distance = _library_hash_distance(f1.colorhash, f2.colorhash)
    # Blur and colour carry most of the weight: lettering may change while the
    # illustration remains the same.  Sharp pixels and edges prevent flat,
    # same-colour pages from being reported as a confident match.
    score = (
        0.42 * (1.0 - blurred_mae)
        + 0.26 * histogram
        + 0.17 * (1.0 - pixel_mae)
        + 0.10 * (1.0 - edge_mae)
        + 0.05 * (1.0 - dhash_distance / 64.0)
    )
    return (score, pixel_mae, blurred_mae, edge_mae, dhash_distance, histogram,
            phash_distance, whash_distance, colorhash_distance)


def _resolve_reference(book: Path, page: Path, reference: str) -> Path | None:
    value = urllib.parse.unquote(html.unescape(reference)).split("#", 1)[0].split("?", 1)[0]
    if not value or value.startswith("data:"):
        return None
    candidate = (page.parent / value).resolve()
    try:
        candidate.relative_to(book.resolve())
    except ValueError:
        return None
    if candidate.is_file() and candidate.suffix.lower() in IMAGE_EXTENSIONS:
        return candidate
    # EPUBs occasionally differ only in case between href and the asset name.
    folded = {p.name.casefold(): p for p in book.rglob("*") if p.is_file()}
    return folded.get(candidate.name.casefold())


def collect_book(book: Path) -> list[Asset]:
    paths = image_files(book)
    by_path = {path.resolve(): Asset(
        path=path,
        relative=path.relative_to(book).as_posix(),
        name=path.name,
        size=path.stat().st_size,
        sha256=sha256(path),
    ) for path in paths}
    by_name = {path.name.casefold(): path for path in paths}
    reference_re = re.compile(r"<(?:img|image)\b[^>]*?\b(?:src|href|xlink:href)\s*=\s*['\"]([^'\"]+)", re.I | re.S)
    for page in sorted((p for p in book.rglob("*") if p.is_file() and p.suffix.lower() in XHTML_EXTENSIONS),
                       key=lambda p: p.relative_to(book).as_posix().casefold()):
        try:
            text = page.read_text(encoding="utf-8-sig", errors="ignore")
        except OSError:
            continue
        page_relative = page.relative_to(book).as_posix()
        page_header = pairing_header_of(page.name)
        page_kind = page_role(page.name)
        for slot, reference in enumerate(reference_re.findall(text)):
            resolved = _resolve_reference(book, page, reference)
            if resolved is None:
                # Keep a useful unresolved reference in the report without
                # manufacturing an asset record.
                continue
            asset = by_path.get(resolved.resolve())
            if asset is None:
                asset = by_name.get(resolved.name.casefold()) and by_path.get(by_name[resolved.name.casefold()].resolve())
            if asset is not None:
                asset.references.append(page_relative)
                page_key = page_header or page_relative
                if page_key not in asset.pages:
                    asset.pages.append(page_key)

                # A body image is only name-rule equivalent when both sides
                # point to the same normalized XHTML header and image slot.
                # Packaging/illustration images use their semantic filename
                # family instead: Japanese p-fmatter pages have no shared
                # page header with the Chinese Illustrations page.
                family, number = image_name_family(asset.name)
                if family == "body" and page_kind == "body" and page_header:
                    location = f"header:{page_header.casefold()}:{slot}"
                elif family != "other":
                    location = f"family:{family}:{number if number is not None else 0}"
                elif page_kind != "body":
                    location = f"role:{page_kind}:{slot}"
                else:
                    location = f"page:{page_relative}:{slot}"
                if location not in asset.locations:
                    asset.locations.append(location)
    return list(by_path.values())


def _page_overlap(first: Asset, second: Asset) -> int:
    return len(set(first.pages).intersection(second.pages))


def _choose_exact(cn: Asset, candidates: list[Asset]) -> Asset:
    return max(candidates, key=lambda jp: (
        _page_overlap(cn, jp),
        int(cn.name.casefold() == jp.name.casefold()),
        int(cn.path.stem.casefold() == jp.path.stem.casefold()),
        -len(jp.relative),
    ))


def _asset_record(asset: Asset) -> dict:
    return asset.json()


def _match_paths(row: dict) -> str:
    japanese_paths = [row["japanese"]["path"]]
    japanese_paths.extend(asset["path"] for asset in row.get("japanese_parts", []))
    return " + ".join(f"日 `{path}`" for path in japanese_paths)


def compare_book(cn_assets: list[Asset], jp_assets: list[Asset]) -> tuple[list[Match], list[Asset], list[Asset]]:
    # Decode every asset once so unmatched files still carry dimensions and a
    # useful decode error in the report.
    for asset in (*cn_assets, *jp_assets):
        feature(asset)
    matches: list[Match] = []
    used_cn: set[Path] = set()
    used_jp: set[Path] = set()
    by_hash: dict[str, list[Asset]] = defaultdict(list)
    for asset in jp_assets:
        by_hash[asset.sha256].append(asset)
    for cn in cn_assets:
        candidates = [jp for jp in by_hash.get(cn.sha256, []) if jp.path not in used_jp]
        if not candidates:
            continue
        jp = _choose_exact(cn, candidates)
        used_cn.add(cn.path)
        used_jp.add(jp.path)
        kind = "exact_bytes_same_name" if cn.name.casefold() == jp.name.casefold() else "exact_bytes_name_different"
        matches.append(Match(cn, jp, kind, score=1.0, pixel_mae=0.0, blurred_mae=0.0,
                             edge_mae=0.0, histogram=1.0, dhash_distance=0,
                             phash_distance=0, whash_distance=0, colorhash_distance=0,
                             reason="SHA-256 相同"))

    # A Chinese double-page asset can be a horizontal composition of two
    # Japanese single-page assets (for example i-232-233 <- i-232 + i-233).
    # Keep this as one correspondence record while retaining both Japanese
    # resources in the report and marking both as consumed.
    remaining_cn = [asset for asset in cn_assets if asset.path not in used_cn]
    remaining_jp = [asset for asset in jp_assets if asset.path not in used_jp]
    jp_by_number: dict[str, list[Asset]] = defaultdict(list)
    for asset in remaining_jp:
        number = body_number_key(asset.name)
        if number is not None:
            jp_by_number[number].append(asset)
    for cn in remaining_cn:
        parts = body_number_parts(cn.name)
        if parts is None or cn.layout != "double_page_candidate":
            continue
        japanese_parts: list[Asset] = []
        for part in parts:
            candidates = [asset for asset in jp_by_number.get(str(part), []) if asset.path not in used_jp]
            if len(candidates) != 1:
                japanese_parts = []
                break
            japanese_parts.append(candidates[0])
        if len(japanese_parts) != 2 or any(asset.layout == "double_page_candidate" for asset in japanese_parts):
            continue
        matches.append(Match(
            cn,
            japanese_parts[0],
            "name_rule_same_content",
            reason="中文双页范围编号对应日文两张连续单页",
            japanese_parts=japanese_parts[1:],
        ))
        used_cn.add(cn.path)
        for asset in japanese_parts:
            used_jp.add(asset.path)

    # Filename rules are deliberately applied before perceptual matching. A
    # stable page/slot or semantic image family is stronger than a hash score
    # when lettering was replaced, but weaker than an exact byte match.
    rule_candidates: list[tuple[int, int, Asset, Asset, str]] = []
    remaining_cn = [asset for asset in cn_assets if asset.path not in used_cn]
    remaining_jp = [asset for asset in jp_assets if asset.path not in used_jp]
    for cn in remaining_cn:
        for jp in remaining_jp:
            matched, label = name_rule_match(cn, jp)
            if not matched:
                continue
            overlap = len(set(cn.locations).intersection(jp.locations))
            rule_candidates.append((overlap, int(cn.name.casefold() == jp.name.casefold()), cn, jp, label))
    for overlap, same_name, cn, jp, label in sorted(
        rule_candidates,
        key=lambda row: (row[0], row[1], -len(row[2].relative), -len(row[3].relative)),
        reverse=True,
    ):
        if cn.path in used_cn or jp.path in used_jp:
            continue
        matches.append(Match(
            cn,
            jp,
            "name_rule_same_content",
            reason=f"文件名规则匹配：{label}；共同位置键 {overlap} 个",
        ))
        used_cn.add(cn.path)
        used_jp.add(jp.path)

    candidates: list[tuple[float, int, Asset, Asset, tuple[float, float, float, float, int, float, int | None, int | None, int | None]]] = []
    remaining_cn = [asset for asset in cn_assets if asset.path not in used_cn]
    remaining_jp = [asset for asset in jp_assets if asset.path not in used_jp]
    for cn in remaining_cn:
        for jp in remaining_jp:
            metrics = compare(cn, jp)
            if metrics is None:
                continue
            (score, pixel_mae, blurred_mae, edge_mae, dhash_distance, histogram,
             phash_distance, whash_distance, colorhash_distance) = metrics
            # Strong match: exact visual content after resampling/encoding.
            strong = (pixel_mae <= 0.025 and blurred_mae <= 0.02
                      and (dhash_distance <= 4 or
                           (phash_distance is not None and phash_distance <= 6
                            and (whash_distance is None or whash_distance <= 8))))
            # Possible translated lettering/font substitution.  This is a
            # review queue, not an assertion that the images are equivalent.
            text_change = (score >= 0.875 and blurred_mae <= 0.105 and dhash_distance <= 24
                           and (phash_distance is None or phash_distance <= 18)
                           and (histogram >= 0.86 or (edge_mae <= 0.03 and dhash_distance <= 8)))
            if strong or text_change:
                page_bonus = _page_overlap(cn, jp)
                candidates.append((score, page_bonus, cn, jp, metrics))
    for score, page_bonus, cn, jp, metrics in sorted(candidates, key=lambda row: (row[0], row[1]), reverse=True):
        if cn.path in used_cn or jp.path in used_jp:
            continue
        (_, pixel_mae, blurred_mae, edge_mae, dhash_distance, histogram,
         phash_distance, whash_distance, colorhash_distance) = metrics
        strong = (pixel_mae <= 0.025 and blurred_mae <= 0.02
                  and (dhash_distance <= 4 or
                       (phash_distance is not None and phash_distance <= 6
                        and (whash_distance is None or whash_distance <= 8))))
        kind = "decoded_pixels_name_different" if cn.name.casefold() != jp.name.casefold() else "decoded_pixels_same_name"
        reason = "缩放后像素几乎一致"
        if not strong:
            if histogram < 0.86 and edge_mae <= 0.03:
                kind = "possible_same_content"
                reason = "结构和感知哈希相似，但颜色/灰度渲染差异较大；需要视觉复核"
            else:
                kind = "possible_same_content_text_or_font_changed"
                reason = "模糊结构/颜色相似，可能仅有文字或字体替换；需要视觉复核"
        matches.append(Match(cn, jp, kind, score, pixel_mae, blurred_mae, edge_mae,
                             histogram, dhash_distance, phash_distance, whash_distance,
                             colorhash_distance, reason))
        used_cn.add(cn.path)
        used_jp.add(jp.path)
    return matches, [a for a in cn_assets if a.path not in used_cn], [a for a in jp_assets if a.path not in used_jp]


def _display_path(asset: Asset) -> str:
    return asset.relative.replace("\\", "/")


def render_markdown(report: dict) -> str:
    lines = ["# 中日 EPUB 图片对应检查", "", f"缓存：`{report['cache']}`", "",
             "算法候选（尤其是 `possible_same_content_text_or_font_changed`）需要人工查看原图确认。", ""]
    summary = report["summary"]
    lines += ["## 汇总", "", "| 项目 | 数量 |", "| --- | ---: |",
              f"| 配对书籍 | {summary['paired_books']} |",
              f"| 中日图片总数 | {summary['chinese_images']} / {summary['japanese_images']} |",
              f"| 已匹配中文 / 日文图片 | {summary['matched_chinese_images']} / {summary['matched_japanese_images']} |",
              f"| 中方未匹配 | {summary['missing_chinese']} |",
              f"| 日方未匹配 | {summary['missing_japanese']} |",
              f"| 按文件名规则匹配 | {summary['name_rule_matches']} |",
              f"| 名称不同且算法确认同图 | {summary['name_different_same_content']} |",
              f"| 疑似同图（渲染/颜色差异） | {summary['possible_same_content']} |",
              f"| 疑似文字/字体变化 | {summary['possible_text_or_font_changes']} |", "",
              f"| 同编号单双页尺寸冲突 | {summary['layout_mismatches']} |", "",
              f"| 中文双页合图对应日文单页组合 | {summary['composite_range_matches']} |", "",
              f"算法后端：ImageHash={'启用' if report['algorithms']['imagehash'] else '未安装（使用 Pillow 回退）'}。", ""]
    if report["unpaired_books"]:
        lines += ["## 未配对书籍", ""]
        for row in report["unpaired_books"]:
            lines.append(f"- `{row['side']}/{row['book']}`：{row['reason']}")
        lines.append("")
    for book in report["books"]:
        lines += [f"## {book['chinese_book']} ↔ {book['japanese_book']}", "",
                  f"图片：{book['chinese_images']} / {book['japanese_images']}；已匹配：中 {book['matched_chinese_images']} / 日 {book['matched_japanese_images']}；未匹配：中 {len(book['missing_chinese'])}、日 {len(book['missing_japanese'])}", ""]
        groups = [
            ("命名规则匹配", [m for m in book["matches"] if m["classification"] == "name_rule_same_content"]),
            ("名称不同且算法确认同图", [m for m in book["matches"] if m["classification"] in {"exact_bytes_name_different", "decoded_pixels_name_different"}]),
            ("精确字节匹配", [m for m in book["matches"] if m["classification"].startswith("exact_bytes")]),
            ("解码后图片匹配", [m for m in book["matches"] if m["classification"].startswith("decoded_pixels")]),
            ("疑似同图但有渲染/颜色差异（待视觉复核）", [m for m in book["matches"] if m["classification"] == "possible_same_content"]),
            ("疑似仅文字/字体变化（待视觉复核）", [m for m in book["matches"] if m["classification"] == "possible_same_content_text_or_font_changed"]),
        ]
        for title, rows in groups:
            if not rows:
                continue
            lines += [f"### {title}", ""]
            for row in rows:
                score = f"score={row['score']}，" if row["score"] is not None else ""
                lines.append(f"- 中 `{row['chinese']['path']}` ↔ {_match_paths(row)}（{score}{row['reason']}）")
            lines.append("")
        if book["missing_chinese"]:
            lines += ["### 中文有、日文无对应", ""]
            lines += [f"- `{row['path']}`" for row in book["missing_chinese"]] + [""]
        if book["missing_japanese"]:
            lines += ["### 日文有、中文无对应", ""]
            lines += [f"- `{row['path']}`" for row in book["missing_japanese"]] + [""]
        if book["layout_mismatches"]:
            lines += ["### 同编号但单双页尺寸类别冲突（优先检查是否错位）", ""]
            for row in book["layout_mismatches"]:
                lines.append(
                    f"- 中 `{row['chinese']['path']}`（{row['chinese']['width']}x{row['chinese']['height']}，{row['chinese']['layout']}）"
                    f" ↔ 日 `{row['japanese']['path']}`（{row['japanese']['width']}x{row['japanese']['height']}，{row['japanese']['layout']}）"
                )
            lines.append("")
    return "\n".join(lines)


def scan(cache: Path, pattern: str) -> dict:
    cn_root, jp_root = cache / "chinese-text", cache / "japanese-text"
    cn_dirs = {book_id(d.name): d for d in cn_root.iterdir() if d.is_dir() and book_id(d.name)} if cn_root.is_dir() else {}
    jp_dirs = {book_id(d.name): d for d in jp_root.iterdir() if d.is_dir() and book_id(d.name)} if jp_root.is_dir() else {}
    cn_dirs = {key: value for key, value in cn_dirs.items() if Path(value.name).match(pattern)}
    books: list[dict] = []
    unpaired: list[dict] = []
    for cn_id, cn_dir in sorted(cn_dirs.items()):
        jp_id = japanese_book_id(cn_id)
        if cn_id in NON_PAIR_WORK_IDS:
            unpaired.append({"side": "pair", "book": cn_id, "reason": "项目已知非同一作品（画集/短篇），默认跳过"})
            continue
        jp_dir = jp_dirs.get(jp_id)
        if jp_dir is None:
            unpaired.append({"side": "chinese-text", "book": cn_dir.name, "reason": f"找不到日文作品号 {jp_id}"})
            continue
        cn_assets, jp_assets = collect_book(cn_dir), collect_book(jp_dir)
        # Decode dimensions before applying the filename-number layout check.
        for asset in (*cn_assets, *jp_assets):
            feature(asset)
        matches, missing_cn, missing_jp = compare_book(cn_assets, jp_assets)
        layout_mismatches = [
            {"chinese": chinese.json(), "japanese": japanese.json()}
            for chinese, japanese in body_layout_mismatches(cn_assets, jp_assets)
        ]
        books.append({
            "id": cn_id,
            "chinese_book": cn_dir.name,
            "japanese_book": jp_dir.name,
            "chinese_images": len(cn_assets),
            "japanese_images": len(jp_assets),
            "matched": len(matches),
            "matched_chinese_images": len(matches),
            "matched_japanese_images": sum(1 + len(match.japanese_parts) for match in matches),
            "matches": [m.json() for m in sorted(matches, key=lambda m: (m.kind, m.chinese.relative.casefold()))],
            "missing_chinese": [_asset_record(a) for a in missing_cn],
            "missing_japanese": [_asset_record(a) for a in missing_jp],
            "layout_mismatches": layout_mismatches,
        })
    requested_jp_ids = {japanese_book_id(key) for key in cn_dirs}
    for jp_id, jp_dir in sorted(jp_dirs.items()):
        if jp_id not in requested_jp_ids and Path(jp_dir.name).match(pattern):
            unpaired.append({"side": "japanese-text", "book": jp_dir.name, "reason": "找不到中文作品号"})
    summary = {
        "paired_books": len(books),
        "chinese_images": sum(book["chinese_images"] for book in books),
        "japanese_images": sum(book["japanese_images"] for book in books),
        "matched_images": sum(book["matched"] for book in books),
        "matched_chinese_images": sum(book["matched_chinese_images"] for book in books),
        "matched_japanese_images": sum(book["matched_japanese_images"] for book in books),
        "missing_chinese": sum(len(book["missing_chinese"]) for book in books),
        "missing_japanese": sum(len(book["missing_japanese"]) for book in books),
        "name_rule_matches": sum(sum(m["classification"] == "name_rule_same_content" for m in book["matches"]) for book in books),
        "exact_bytes_name_different": sum(sum(m["classification"] == "exact_bytes_name_different" for m in book["matches"]) for book in books),
        "name_different_same_content": sum(sum(m["classification"] in {"exact_bytes_name_different", "decoded_pixels_name_different", "name_rule_same_content"} and m["chinese"]["name"].casefold() != m["japanese"]["name"].casefold() for m in book["matches"]) for book in books),
        "possible_same_content": sum(sum(m["classification"] == "possible_same_content" for m in book["matches"]) for book in books),
        "possible_text_or_font_changes": sum(sum(m["classification"] == "possible_same_content_text_or_font_changed" for m in book["matches"]) for book in books),
        "layout_mismatches": sum(len(book["layout_mismatches"]) for book in books),
        "composite_range_matches": sum(sum(bool(m.get("japanese_parts")) for m in book["matches"]) for book in books),
    }
    return {
        "cache": cache.as_posix(),
        "pattern": pattern,
        "algorithms": {
            "sha256": True,
            "pillow_thumbnail_metrics": True,
            "imagehash": imagehash is not None,
            "imagehash_algorithms": ["phash", "dhash", "whash", "colorhash"] if imagehash is not None else [],
        },
        "summary": summary,
        "unpaired_books": unpaired,
        "books": books,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="比较缓存中成对中文/日文 EPUB 的图片内容")
    parser.add_argument("--cache", type=Path, default=Path(".cache/epub-work"), help="EPUB 缓存根目录")
    parser.add_argument("--output", type=Path, default=None, help="报告目录；默认写入 <cache>/image-comparison")
    parser.add_argument("--pattern", default="*", help="按中文书目录名筛选，例如 '*S1_01*'")
    args = parser.parse_args(argv)
    cache = args.cache.resolve()
    if not (cache / "chinese-text").is_dir() or not (cache / "japanese-text").is_dir():
        parser.error(f"缓存必须包含 chinese-text/ 和 japanese-text/：{cache}")
    report = scan(cache, args.pattern)
    output = (args.output or cache / "image-comparison").resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "report.md").write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"报告：{output / 'report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
