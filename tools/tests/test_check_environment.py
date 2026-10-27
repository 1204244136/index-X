from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import check_environment as environment


class FakeDevice:
    def __init__(self, device_type):
        self.type = device_type

    def __str__(self):
        return "cuda:0" if self.type == "cuda" else self.type


def vector_modules(*, available=True, model_device="cuda", embedding_device="cuda",
                   hip="test-rocm", synchronize_error=None):
    embedding = SimpleNamespace(ndim=2, shape=(2, 3))
    numpy = SimpleNamespace(asarray=Mock(return_value=embedding),
                            isfinite=Mock(return_value=SimpleNamespace(all=lambda: True)))
    tensor = Mock()
    tensor.device = FakeDevice(embedding_device)
    model = SimpleNamespace(device=FakeDevice(model_device), encode=Mock(return_value=tensor))
    transformer = Mock(return_value=model)
    torch = SimpleNamespace(
        cuda=SimpleNamespace(
            is_available=Mock(return_value=available), current_device=Mock(return_value=0),
            get_device_name=Mock(return_value="AMD Radeon Test GPU"),
            synchronize=Mock(side_effect=synchronize_error),
        ),
        version=SimpleNamespace(hip=hip, cuda=None if hip else "test-cuda"),
        is_tensor=Mock(side_effect=lambda value: value is tensor),
    )
    return {
        "numpy": numpy, "torch": torch,
        "sentence_transformers": SimpleNamespace(SentenceTransformer=transformer),
    }, transformer, model, tensor


class EnvironmentTests(unittest.TestCase):
    def test_core_is_standard_library_and_does_not_require_external_commands(self):
        with patch.object(environment.importlib, "import_module") as load, \
                patch.object(environment.shutil, "which", return_value=None):
            report = environment.check_environment()
        self.assertTrue(report["ok"])
        self.assertEqual(report["dependencies"], [])
        self.assertEqual(report["model"]["status"], "not_checked")
        self.assertIn("git", report["commands"])
        self.assertTrue(all(path is None for path in report["commands"].values()))
        self.assertTrue(report["python"]["executable"])
        self.assertTrue(report["python"]["version"])
        load.assert_not_called()

    def test_missing_required_dependency_fails_but_preserves_all_results(self):
        def load(name):
            if name == "torch":
                raise ImportError("missing torch")
            return SimpleNamespace(__version__="test")
        with patch.object(environment.importlib, "import_module", side_effect=load), \
                patch.object(environment.metadata, "version", return_value="test"):
            report = environment.check_environment("vector")
        self.assertFalse(report["ok"])
        self.assertEqual([d["name"] for d in report["dependencies"]],
                         ["numpy", "torch", "sentence-transformers"])
        self.assertIn("missing torch", report["dependencies"][1]["error"])
        self.assertTrue(report["dependencies"][2]["available"])

    def test_broken_import_is_an_environment_failure(self):
        with patch.object(environment.importlib, "import_module", side_effect=OSError("DLL load failed")):
            result = environment.probe_dependency("torch", "torch")
        self.assertFalse(result["available"])
        self.assertIn("DLL load failed", result["error"])

    def test_missing_imagehash_does_not_block_maintenance(self):
        def load(name):
            if name == "imagehash":
                raise ImportError("optional missing")
            return SimpleNamespace()
        with patch.object(environment.importlib, "import_module", side_effect=load), \
                patch.object(environment.metadata, "version", return_value="test"):
            report = environment.check_environment("maintenance")
        self.assertTrue(report["ok"])
        self.assertFalse(report["dependencies"][-1]["required"])
        self.assertFalse(report["dependencies"][-1]["available"])

    def test_model_is_not_loaded_without_explicit_request(self):
        with patch.object(environment, "probe_dependency", return_value={"required": True, "available": True}), \
                patch.object(environment, "probe_model") as model:
            report = environment.check_environment("vector")
        self.assertTrue(report["ok"])
        self.assertFalse(report["model"]["requested"])
        model.assert_not_called()

    def test_model_is_not_loaded_when_dependencies_are_broken(self):
        with patch.object(environment, "probe_dependency", return_value={"required": True, "available": False}), \
                patch.object(environment, "probe_model") as model:
            report = environment.check_environment("vector", model=True)
        self.assertFalse(report["ok"])
        self.assertEqual(report["model"]["status"], "blocked")
        model.assert_not_called()

    def test_model_probe_stays_offline_and_encodes_input(self):
        embedding = SimpleNamespace(ndim=2, shape=(2, 3))
        numpy = SimpleNamespace(asarray=Mock(return_value=embedding),
                                isfinite=Mock(return_value=SimpleNamespace(all=lambda: True)))
        model = Mock()
        transformer = Mock(return_value=model)
        modules = {"numpy": numpy, "sentence_transformers": SimpleNamespace(SentenceTransformer=transformer)}
        with patch.object(environment.importlib, "import_module", side_effect=modules.__getitem__):
            result = environment.probe_model()
        self.assertEqual(result["status"], "ok")
        self.assertTrue(transformer.call_args.kwargs["local_files_only"])
        self.assertEqual(transformer.call_args.kwargs["device"], "cpu")
        self.assertEqual(transformer.call_args.kwargs["model_kwargs"], {"attn_implementation": "eager"})
        self.assertEqual(len(model.encode.call_args.args[0]), 2)
        self.assertFalse(model.encode.call_args.kwargs["show_progress_bar"])

    def test_missing_local_model_is_a_failure(self):
        modules = {"numpy": SimpleNamespace(), "sentence_transformers": SimpleNamespace(
            SentenceTransformer=Mock(side_effect=OSError("not cached")))}
        with patch.object(environment.importlib, "import_module", side_effect=modules.__getitem__):
            result = environment.probe_model()
        self.assertEqual(result["status"], "error")
        self.assertIn("not cached", result["message"])
        self.assertIn("不下载模型", result["message"])

    def test_invalid_model_output_does_not_pass(self):
        numpy = SimpleNamespace(asarray=Mock(return_value=SimpleNamespace(ndim=1, shape=(2,))))
        modules = {"numpy": numpy, "sentence_transformers": SimpleNamespace(SentenceTransformer=Mock())}
        with patch.object(environment.importlib, "import_module", side_effect=modules.__getitem__):
            result = environment.probe_model()
        self.assertEqual(result["status"], "error")
        self.assertIn("有效", result["message"])

    def test_gpu_model_and_embeddings_are_verified_on_rocm_before_cpu_copy(self):
        modules, transformer, model, tensor = vector_modules()
        with patch.object(environment.importlib, "import_module", side_effect=modules.__getitem__):
            result = environment.probe_model(device="cuda")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["backend"], "rocm")
        self.assertEqual(result["hip_version"], "test-rocm")
        self.assertEqual(result["gpu_name"], "AMD Radeon Test GPU")
        self.assertEqual(result["model_device"], "cuda:0")
        self.assertEqual(result["embedding_device"], "cuda:0")
        self.assertTrue(result["encoded_on_gpu"])
        self.assertTrue(transformer.call_args.kwargs["local_files_only"])
        self.assertEqual(transformer.call_args.kwargs["device"], "cuda")
        self.assertTrue(model.encode.call_args.kwargs["convert_to_tensor"])
        self.assertNotIn("convert_to_numpy", model.encode.call_args.kwargs)
        modules["torch"].cuda.synchronize.assert_called_once_with()
        tensor.detach.return_value.cpu.return_value.numpy.assert_called_once_with()

    def test_forced_gpu_unavailable_does_not_fall_back(self):
        modules, transformer, model, _ = vector_modules(available=False)
        with patch.object(environment.importlib, "import_module", side_effect=modules.__getitem__):
            result = environment.probe_model(device="cuda")
        self.assertEqual(result["status"], "error")
        self.assertIn("未回退 CPU", result["message"])
        self.assertFalse(result["encoded_on_gpu"])
        transformer.assert_not_called()
        model.encode.assert_not_called()

    def test_cpu_model_cannot_pass_forced_gpu_probe(self):
        modules, _, model, _ = vector_modules(model_device="cpu")
        with patch.object(environment.importlib, "import_module", side_effect=modules.__getitem__):
            result = environment.probe_model(device="cuda")
        self.assertEqual(result["status"], "error")
        self.assertIn("模型未驻留 GPU", result["message"])
        self.assertFalse(result["encoded_on_gpu"])
        model.encode.assert_not_called()

    def test_cpu_embeddings_cannot_pass_forced_gpu_probe(self):
        modules, _, _, tensor = vector_modules(embedding_device="cpu")
        with patch.object(environment.importlib, "import_module", side_effect=modules.__getitem__):
            result = environment.probe_model(device="cuda")
        self.assertEqual(result["status"], "error")
        self.assertIn("编码结果未驻留 GPU", result["message"])
        self.assertFalse(result["encoded_on_gpu"])
        tensor.detach.assert_not_called()

    def test_async_gpu_kernel_error_fails_probe(self):
        modules, _, _, tensor = vector_modules(synchronize_error=RuntimeError("GPU kernel failed"))
        with patch.object(environment.importlib, "import_module", side_effect=modules.__getitem__):
            result = environment.probe_model(device="cuda")
        self.assertEqual(result["status"], "error")
        self.assertIn("GPU kernel failed", result["message"])
        self.assertFalse(result["encoded_on_gpu"])
        tensor.detach.assert_not_called()

    def test_auto_selects_gpu_when_available_and_cpu_otherwise(self):
        for available in (True, False):
            with self.subTest(available=available):
                modules, transformer, model, _ = vector_modules(
                    available=available, model_device="cuda" if available else "cpu",
                )
                with patch.object(environment.importlib, "import_module", side_effect=modules.__getitem__):
                    result = environment.probe_model(device="auto")
                self.assertEqual(result["status"], "ok")
                self.assertEqual(result["device"], "cuda" if available else "cpu")
                self.assertEqual(result["encoded_on_gpu"], available)
                self.assertEqual(transformer.call_args.kwargs["device"], result["device"])
                if not available:
                    self.assertTrue(model.encode.call_args.kwargs["convert_to_numpy"])
                    modules["torch"].cuda.synchronize.assert_not_called()

    def test_cuda_build_is_distinguished_from_rocm(self):
        modules, _, _, _ = vector_modules(hip=None)
        with patch.object(environment.importlib, "import_module", side_effect=modules.__getitem__):
            result = environment.probe_model(device="cuda")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["backend"], "cuda")
        self.assertEqual(result["cuda_version"], "test-cuda")
        self.assertIsNone(result["hip_version"])

    def test_gpu_json_contains_actual_model_probe_results(self):
        modules, _, _, _ = vector_modules()
        output, errors = io.StringIO(), io.StringIO()
        with patch.object(environment.importlib, "import_module", side_effect=modules.__getitem__), \
                patch.object(environment.metadata, "version", return_value="test"), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = environment.main(["--profile", "vector", "--model", "--device", "cuda", "--json"])
        self.assertEqual(code, 0)
        report = json.loads(output.getvalue())
        self.assertTrue(report["ok"])
        self.assertEqual(report["model"]["requested_device"], "cuda")
        self.assertEqual(report["model"]["backend"], "rocm")
        self.assertTrue(report["model"]["encoded_on_gpu"])
        self.assertEqual(errors.getvalue(), "")

    def test_gpu_json_failure_returns_environment_error(self):
        modules, _, _, _ = vector_modules(available=False)
        output, errors = io.StringIO(), io.StringIO()
        with patch.object(environment.importlib, "import_module", side_effect=modules.__getitem__), \
                patch.object(environment.metadata, "version", return_value="test"), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = environment.main(["--profile", "vector", "--model", "--device", "cuda", "--json"])
        self.assertEqual(code, 2)
        self.assertFalse(json.loads(output.getvalue())["ok"])
        self.assertIn("未回退 CPU", errors.getvalue())

    def test_explicit_device_requires_vector_model(self):
        for args in (["--device", "cpu"], ["--profile", "vector", "--device", "cuda"],
                     ["--profile", "maintenance", "--model", "--device", "auto"]):
            with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()), \
                    self.assertRaises(SystemExit) as error:
                environment.main(args)
            self.assertEqual(error.exception.code, 2)
        with self.assertRaises(ValueError):
            environment.check_environment("core", device="cuda")

    def test_json_is_complete_even_when_import_prints_and_fails(self):
        def noisy_import(name):
            print("package startup")
            raise ImportError("missing " + name)
        output, errors = io.StringIO(), io.StringIO()
        with patch.object(environment.importlib, "import_module", side_effect=noisy_import), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = environment.main(["--profile", "vector", "--json"])
        self.assertEqual(code, 2)
        report = json.loads(output.getvalue())
        self.assertFalse(report["ok"])
        self.assertEqual(len(report["dependencies"]), 3)
        self.assertIn("commands", report)
        self.assertIn("未核验模型", report["model"]["message"])
        self.assertIn("package startup", errors.getvalue())
        self.assertIn("错误:", errors.getvalue())

    def test_model_requires_vector_profile(self):
        with self.assertRaises(ValueError):
            environment.check_environment("maintenance", model=True)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            environment.main(["--model"])
        self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
