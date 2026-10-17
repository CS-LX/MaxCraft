"""Build a self-contained Max-side zip; Minecraft/JDK/Gradle are separate."""
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parents[1]
if not (root / 'maxcraft/_native/atomics.dll').exists():
    raise SystemExit('Build native/atomics.c first: scripts/build_native.cmd')
output = root / 'dist/MaxCraft-0.1.3.zip'
output.parent.mkdir(exist_ok=True)
files = ['README.md', 'THIRD-PARTY-SKYCRAFT-LICENSE.txt', 'launch_maxcraft.py',
         'install_maxcraft.py', 'Install_MaxCraft.ms']
with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
    for name in files:
        archive.write(root / name, name)
    for folder in ('maxcraft', 'scripts', 'docs', 'native', 'tests'):
        for path in (root / folder).rglob('*'):
            if (path.is_file() and '__pycache__' not in path.parts
                    and path.name != 'installation.json'
                    and path.suffix not in ('.pyc', '.obj', '.lib', '.exp')):
                archive.write(path, path.relative_to(root))
print(output)

