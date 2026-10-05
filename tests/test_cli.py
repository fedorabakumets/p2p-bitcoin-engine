import os
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from app.health import create_health_app

ROOT = Path(__file__).resolve().parents[1]


def _env(**updates: str) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("BOT_TOKEN", None)
    env.update(updates)
    return env


def test_missing_token_exits_without_traceback() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "app.main"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=_env(BOT_TOKEN=""),
        check=False,
    )
    assert result.returncode == 1
    assert "BOT_TOKEN" in result.stderr
    assert "Traceback" not in result.stderr
    assert "Traceback" not in result.stdout


def test_dry_run_without_token() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "app.main", "--dry-run"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=_env(),
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Получите: 2000 ₽" in result.stdout
    assert "Наценка: 18%" in result.stdout
    assert "К оплате: 2360 ₽" in result.stdout
    assert "Уйдёт: 0.00033333 BTC" in result.stdout
    assert "Курс действует ещё 2 мин" in result.stdout
    assert "dry-run ok" in result.stdout
    assert "Traceback" not in result.stderr


def test_handlers_do_not_hardcode_markup() -> None:
    source = (ROOT / "app" / "bot" / "client" / "handlers.py").read_text(encoding="utf-8")
    assert "1.18" not in source
    assert "1800" not in source


def test_healthz() -> None:
    client = TestClient(create_health_app())
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
