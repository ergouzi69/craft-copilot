"""配置加载：.env 文件 → os.environ（零依赖，不覆盖已有环境变量）

对应 harness"环境子系统"：让环境自描述（.env 模板 + 锁版本 requirements）。
复用 customer-copilot 验证过的 env_loader 思路，独立实现保持本项目自包含。
"""
import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def load_env_file() -> None:
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:   # 已有环境变量优先
            os.environ[key] = value


def get(key: str, default: str = "") -> str:
    return os.environ.get(key, default)
