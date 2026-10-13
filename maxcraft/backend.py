"""Launch the isolated development backend without reading launcher credentials."""
import json
from pathlib import Path
import shutil
import subprocess


def project_root():
    config = Path(__file__).parent / 'installation.json'
    if config.is_file():
        return Path(json.loads(config.read_text(encoding='utf-8'))['project_root'])
    return Path(__file__).resolve().parents[1]


def launch():
    root = project_root()
    script = root / 'scripts/start-dev.ps1'
    if not script.is_file():
        raise RuntimeError('找不到 Minecraft 启动脚本，请从完整解压目录重新安装 MaxCraft。')
    shell = shutil.which('pwsh') or shutil.which('powershell')
    if not shell:
        raise RuntimeError('找不到 PowerShell。')
    logs = root / 'logs'
    logs.mkdir(exist_ok=True)
    with (logs / 'minecraft-dev.log').open('w', encoding='utf-8') as output:
        return subprocess.Popen([shell, '-NoProfile', '-File', str(script)], cwd=str(root),
                                stdout=output, stderr=subprocess.STDOUT,
                                creationflags=subprocess.CREATE_NO_WINDOW)

