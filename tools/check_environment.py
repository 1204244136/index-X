#!/usr/bin/env python3
"""Check the current tool runtime without installing packages or switching Python.

Command behavior and dependency groups are documented in tools/README.md.
"""
from __future__ import annotations

import argparse
import contextlib
import importlib
from importlib import metadata
import json
import platform
import shutil
import sys

if __package__:
    from .cli_output import configure_output
else:
    from cli_output import configure_output


PROFILE_DEPENDENCIES = {
    "core": (),
    "maintenance": (("Pillow", "PIL"), ("openpyxl", "openpyxl")),
    "vector": (("numpy", "numpy"), ("torch", "torch"),
               ("sentence-transformers", "sentence_transformers")),
}
EXTERNAL_COMMANDS = ("git", "pwsh", "powershell", "ebook-convert", "calibre-debug")


def probe_dependency(distribution: str, module_name: str, *, required: bool = True) -> dict:
    """Actually import a dependency; metadata alone cannot detect broken DLLs."""
    result = {"name": distribution, "module": module_name, "required": required,
              "available": False, "version": None, "error": None}
    try:
        # Third-party imports sometimes print progress to stdout. Keep JSON intact.
        with contextlib.redirect_stdout(sys.stderr):
            module = importlib.import_module(module_name)
        result["available"] = True
        try:
            result["version"] = metadata.version(distribution)
        except metadata.PackageNotFoundError:
            result["version"] = getattr(module, "__version__", None)
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def probe_model(device: str = "cpu") -> dict:
    """Load the shared semantic model from local files and encode a small input."""
    if __package__:
        from .check_semantic_alignment import EMBEDDING_MODEL_NAME
    else:
        from check_semantic_alignment import EMBEDDING_MODEL_NAME

    result = {
        "requested": True, "status": "error", "name": EMBEDDING_MODEL_NAME,
        "local_files_only": True, "requested_device": device, "device": None,
        "backend": None, "gpu_name": None, "model_device": None,
        "embedding_device": None, "encoded_on_gpu": False,
        "hip_version": None, "cuda_version": None, "message": "",
    }
    try:
        with contextlib.redirect_stdout(sys.stderr):
            if device not in ("cpu", "cuda", "auto"):
                raise ValueError(f"未知模型设备：{device}")
            numpy = importlib.import_module("numpy")
            transformers = importlib.import_module("sentence_transformers")
            selected_device = "cpu"
            torch = None
            if device in ("cuda", "auto"):
                torch = importlib.import_module("torch")
                available = torch.cuda.is_available()
                if device == "cuda" and not available:
                    raise RuntimeError("已要求 CUDA/ROCm GPU，但当前不可用；未回退 CPU")
                if available:
                    selected_device = "cuda"
                    result.update(
                        gpu_name=torch.cuda.get_device_name(torch.cuda.current_device()),
                        hip_version=torch.version.hip, cuda_version=torch.version.cuda,
                    )
            result.update(device=selected_device, backend=(
                "rocm" if result["hip_version"] else "cuda"
            ) if selected_device == "cuda" else "cpu")
            model = transformers.SentenceTransformer(
                EMBEDDING_MODEL_NAME, local_files_only=True, device=selected_device,
                model_kwargs={"attn_implementation": "eager"},
            )
            result["model_device"] = str(model.device)
            inputs = ["環境確認。", "环境检查。"]
            if selected_device == "cuda":
                if model.device.type != "cuda":
                    raise RuntimeError("模型未驻留 GPU，不能确认 GPU 编码通过")
                tensor = model.encode(inputs, convert_to_tensor=True, show_progress_bar=False)
                if not torch.is_tensor(tensor) or tensor.device.type != "cuda":
                    raise RuntimeError("编码结果未驻留 GPU，不能确认 GPU 前向计算通过")
                result["embedding_device"] = str(tensor.device)
                # Synchronize before copying to CPU so asynchronous kernel errors fail.
                torch.cuda.synchronize()
                embeddings = numpy.asarray(tensor.detach().cpu().numpy())
            else:
                embeddings = numpy.asarray(model.encode(
                    inputs, convert_to_numpy=True, show_progress_bar=False,
                ))
                result["embedding_device"] = "cpu"
            if (embeddings.ndim != 2 or embeddings.shape[0] != 2
                    or embeddings.shape[1] == 0 or not numpy.isfinite(embeddings).all()):
                raise ValueError("模型未生成两条有效的有限数值向量")
        result.update(
            status="ok", encoded_on_gpu=selected_device == "cuda",
            message=(f"已使用本地模型完成 {result['backend'].upper()} GPU 编码验证。"
                     if selected_device == "cuda" else "已使用本地模型完成 CPU 编码验证。"),
        )
    except Exception as exc:
        result["message"] = (
            f"本地模型验证失败：{type(exc).__name__}: {exc}；"
            "本工具不下载模型，请按工具合同先准备模型。"
        )
    return result


def check_environment(profile: str = "core", *, model: bool = False, device: str = "cpu") -> dict:
    """Return selected dependency results and informational PATH discovery."""
    if profile not in PROFILE_DEPENDENCIES:
        raise ValueError(f"未知环境分组：{profile}")
    if model and profile != "vector":
        raise ValueError("--model 仅能与 --profile vector 一起使用")
    if device not in ("cpu", "cuda", "auto"):
        raise ValueError(f"未知模型设备：{device}")
    if device != "cpu" and not model:
        raise ValueError("--device 仅能与 --model --profile vector 一起使用")
    dependencies = [probe_dependency(name, module)
                    for name, module in PROFILE_DEPENDENCIES[profile]]
    if profile == "maintenance":
        dependencies.append(probe_dependency("ImageHash", "imagehash", required=False))
    ready = all(item["available"] for item in dependencies if item["required"])
    model_result = {
        "requested": model, "status": "not_checked", "local_files_only": True,
        "message": "未核验模型；依赖可导入不代表 L2 模型已经可用。",
    }
    if model:
        model_result = (probe_model(device=device) if ready else {
            "requested": True, "status": "blocked", "local_files_only": True,
            "requested_device": device,
            "message": "依赖检查未通过，模型尚未核验。",
        })
        ready = ready and model_result["status"] == "ok"
    return {
        "profile": profile, "ok": ready,
        "python": {"executable": sys.executable, "version": platform.python_version()},
        "dependencies": dependencies,
        "commands": {name: shutil.which(name) for name in EXTERNAL_COMMANDS},
        "model": model_result,
    }


def print_report(report: dict) -> None:
    print(f"Python {report['python']['version']}: {report['python']['executable']}")
    print(f"检查分组: {report['profile']}")
    for item in report["dependencies"]:
        requirement = "必需" if item["required"] else "可选增强"
        state = (f"可导入，版本 {item['version'] or '未知'}" if item["available"]
                 else "不可用")
        print(f"  {item['name']} ({requirement}): {state}")
    print("外部命令（仅报告 PATH 可见性，未验证命令执行）:")
    for name, path in report["commands"].items():
        print(f"  {name}: {path or '未发现'}")
    print(report["model"]["message"])
    if report["model"].get("device"):
        model = report["model"]
        print(f"模型设备: {model['model_device']}；后端: {model['backend']}"
              f"；编码结果设备: {model['embedding_device']}")
        if model.get("gpu_name"):
            print(f"GPU: {model['gpu_name']}")
    print("所选环境检查通过。" if report["ok"] else "所选环境检查未通过。")


def main(argv: list[str] | None = None) -> int:
    configure_output()
    parser = argparse.ArgumentParser(description="只读检查当前 Python 的工具环境与可选依赖")
    parser.add_argument("--profile", choices=tuple(PROFILE_DEPENDENCIES), default="core",
                        help="检查分组：基础标准库、图片表格维护或 L2 矢量环境")
    parser.add_argument("--json", action="store_true", help="输出完整 JSON 报告")
    parser.add_argument("--model", action="store_true",
                        help="仅 vector：从本地缓存加载模型并编码验证，不下载")
    parser.add_argument("--device", choices=("cpu", "cuda", "auto"), default=None,
                        help="仅 --model：cpu 默认；cuda 强制 GPU；auto 可回退 CPU")
    args = parser.parse_args(argv)
    if args.model and args.profile != "vector":
        parser.error("--model 仅能与 --profile vector 一起使用")
    if args.device is not None and not (args.model and args.profile == "vector"):
        parser.error("--device 仅能与 --model --profile vector 一起使用")
    report = check_environment(args.profile, model=args.model, device=args.device or "cpu")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_report(report)
    for item in report["dependencies"]:
        if item["required"] and not item["available"]:
            print(f"错误: {item['name']} 无法导入：{item['error']}", file=sys.stderr)
    if report["model"]["status"] in ("error", "blocked"):
        print(f"错误: {report['model']['message']}", file=sys.stderr)
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
