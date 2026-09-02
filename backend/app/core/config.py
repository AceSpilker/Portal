"""应用配置（环境变量对应 api-spec §6.1）。"""

from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ---- 服务 ----
    host: str = "0.0.0.0"
    port: int = 8000
    secret_key: str = "dev-secret-change-me"  # 生产必改
    log_level: str = "info"

    # ---- 数据（SQLite 运行主库；MySQL 仅作镜像目标，见 dev-plan P23）----
    data_dir: Path = Path("./data")
    db_type: str = "sqlite"

    # ---- 监控采集：宿主机只读挂载（为空则读容器自身）----
    host_proc: str = ""
    host_sys: str = ""

    # ---- 可选模块 ----
    docker_sock_enabled: bool = False
    frontend_dist: str = ""  # 前端构建产物目录；为空则尝试相邻 frontend/dist

    # ---- 传输加密（dev-plan P24；api-spec §7）：/api 全部密文传输 ----
    encrypt_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices("encrypt_enabled", "security__encrypt_enabled"),
    )
    transport_rsa_bits: int = 3072


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
