"""The teammate installer must use the verified local model only."""

import hashlib
from zipfile import ZipFile

import pytest

from scripts import local_policy, start_dev


def test_model_package_is_checked_before_import(tmp_path):
    package = tmp_path / "model.zip"
    model = b"small test model"
    with ZipFile(package, "w") as archive:
        archive.writestr(local_policy.GGUF_NAME, model)
        archive.writestr("Modelfile-policy", "untrusted package template")
    target = tmp_path / "extracted"
    target.mkdir()

    installed = local_policy.extract_verified_model(
        package, target,
        expected_size=len(model), expected_sha256=hashlib.sha256(model).hexdigest(),
    )
    assert installed.read_bytes() == model

    with pytest.raises(local_policy.LocalPolicyError, match="SHA-256"):
        local_policy.extract_verified_model(
            package, target,
            expected_size=len(model), expected_sha256="0" * 64,
        )
    assert not installed.exists()


def test_missing_trained_model_does_not_fall_back(monkeypatch):
    monkeypatch.setattr(local_policy, "installed_models", lambda: {"qwen3:8b"})
    with pytest.raises(local_policy.LocalPolicyError, match="--model-package"):
        local_policy.require_local_model()


def test_import_uses_repository_template_not_package_template(tmp_path, monkeypatch):
    model = b"small test model"
    package = tmp_path / "model.zip"
    with ZipFile(package, "w") as archive:
        archive.writestr(local_policy.GGUF_NAME, model)
        archive.writestr("Modelfile-policy", "wrong template")
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "Modelfile-policy").write_text("correct template", encoding="utf-8")
    monkeypatch.setattr(local_policy, "ROOT", root)
    monkeypatch.setattr(local_policy, "GGUF_SIZE", len(model))
    monkeypatch.setattr(local_policy, "GGUF_SHA256", hashlib.sha256(model).hexdigest())
    monkeypatch.setattr(local_policy, "ollama_executable", lambda: "ollama")
    monkeypatch.setattr(local_policy, "installed_models", lambda: {local_policy.MODEL_ID})
    monkeypatch.setattr(local_policy, "verify_model_inference", lambda: None)
    captured = {}

    def fake_run(command, *, cwd, check):
        captured["command"] = command
        captured["template"] = (cwd / "Modelfile-policy").read_text(encoding="utf-8")
        assert (cwd / local_policy.GGUF_NAME).read_bytes() == model

    monkeypatch.setattr(local_policy.subprocess, "run", fake_run)
    local_policy.import_model_package(package)
    assert captured["command"] == ["ollama", "create", "policy-qwen3-8b", "-f", "Modelfile-policy"]
    assert captured["template"] == "correct template"


def test_backend_uses_local_ollama_even_with_old_env(monkeypatch):
    captured = {}

    class FakeProcess:
        pass

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs["env"]
        return FakeProcess()

    monkeypatch.setenv("POLICY_API_BASE_URL", "http://127.0.0.1:8001")
    monkeypatch.setattr(start_dev.subprocess, "Popen", fake_popen)
    children = []
    process = start_dev.start_backend(local_policy.MODEL_ID, 8000, children)

    assert children == [process]
    assert captured["env"]["POLICY_API_BASE_URL"] == local_policy.OLLAMA_URL
    assert captured["env"]["POLICY_API_MODEL"] == local_policy.MODEL_ID
