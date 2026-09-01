"""pytest 全局配置：在导入应用前把 DATA_DIR 指向临时目录，避免污染真实数据。"""
import os
import tempfile

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="portal-test-")
