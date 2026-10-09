#!/usr/bin/env python3
"""图片指纹与尺寸的单一实现（Pillow 可选）。

`compare_epub_images.py`（中日图片核对）与 `import_images.py`（新书图片映射）
共用这里的 dHash，避免两处各写一套「什么算同一张图」。Pillow 缺失时所有函数
返回 `None`／`False`，调用方负责降级或报告，不得因此中断不依赖图片的流程。
"""
from __future__ import annotations

from pathlib import Path

try:  # pragma: no cover - 依赖是否安装由调用方探测
    from PIL import Image, ImageOps
except ImportError:  # pragma: no cover
    Image = None  # type: ignore[assignment]
    ImageOps = None  # type: ignore[assignment]

# 只列 Pillow 能稳妥解码的格式；`epub_structure.IMAGE_SUFFIXES` 是打包校验用的更宽集合
# （另含 avif/bmp/tif/tiff/svg），两者用途不同，不要互相替换。
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".gif", ".webp")


def pillow_available() -> bool:
    return Image is not None


def dhash_image(image, size: int = 8) -> int:
    """基于「横向相邻像素比较」的 dHash；`size` 是每边的比较位数。"""
    small = image.convert("L").resize((size + 1, size), Image.Resampling.LANCZOS)
    pixels = list(small.getdata())
    value = 0
    for row in range(size):
        for column in range(size):
            value = (value << 1) | int(pixels[row * (size + 1) + column]
                                       > pixels[row * (size + 1) + column + 1])
    return value


def dhash(path: Path | str, size: int = 8) -> int | None:
    if not pillow_available():
        return None
    try:
        with Image.open(path) as image:
            return dhash_image(ImageOps.exif_transpose(image), size)
    except (OSError, ValueError):
        return None


def dimensions(path: Path | str) -> tuple[int, int] | None:
    if not pillow_available():
        return None
    try:
        with Image.open(path) as image:
            return image.size
    except (OSError, ValueError):
        return None


def hamming(left: int | None, right: int | None) -> int:
    """两个 dHash 的汉明距离；任一为空返回 -1（不可比）。"""
    if left is None or right is None:
        return -1
    return bin(left ^ right).count("1")


def image_files(directory: Path | str) -> list[Path]:
    return sorted(path for path in Path(directory).iterdir()
                  if path.is_file() and path.suffix.casefold() in IMAGE_SUFFIXES)
