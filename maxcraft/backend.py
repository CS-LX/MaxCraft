"""Launch the isolated development backend without reading launcher credentials."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import winreg


def child_environment():
    # Some Max launchers replace PATH with plugin directories. Restore the user's
    # normal tool search path for this child only; never change Max/global state.
    env = os.environ.copy()
    paths = []
    for hive, key in ((winreg.HKEY_LOCAL_MACHINE, r'SYSTEM\CurrentControlSet\Control\Session Manager\Environment'),
                      (winreg.HKEY_CURRENT_USER, 'Environment')):
        try:
            with winreg.OpenKey(hive, key) as handle:
                paths.append(os.path.expandvars(winreg.QueryValueEx(handle, 'Path')[0]))
        except OSError:
            pass
    paths.append(env.get('PATH', ''))
    env['PATH'] = ';'.join(paths)
    for key in ('PYTHONHOME', 'PYTHONPATH', 'QT_PLUGIN_PATH', 'QML2_IMPORT_PATH'):
        env.pop(key, None)
    return env


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
    env = child_environment()
    shell = shutil.which('pwsh', path=env['PATH']) or shutil.which('powershell', path=env['PATH'])
    if not shell:
        candidate = Path(env.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        shell = str(candidate) if candidate.is_file() else None
    if not shell:
        raise RuntimeError('找不到 PowerShell。')
    logs = root / 'logs'
    logs.mkdir(exist_ok=True)
    with (logs / 'minecraft-dev.log').open('w', encoding='utf-8') as output:
        return subprocess.Popen([shell, '-NoProfile', '-File', str(script)], cwd=str(root),
                                stdout=output, stderr=subprocess.STDOUT,
                                creationflags=subprocess.CREATE_NO_WINDOW, env=env)

