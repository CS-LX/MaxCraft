"""Reuse local official Minecraft assets in the isolated Loom cache (copy only)."""
from pathlib import Path
import json
import os
import shutil

root = Path(__file__).resolve().parents[1]
source = Path(os.environ['APPDATA']) / '.minecraft/assets/objects'
target = root / '.runtime/gradle/caches/fabric-loom/assets'
copied = 0
for index in (target / 'indexes').glob('*.json'):
    for entry in json.loads(index.read_text(encoding='utf-8'))['objects'].values():
        key = entry['hash']
        src, dst = source / key[:2] / key, target / 'objects' / key[:2] / key
        if not dst.exists() and src.is_file() and src.stat().st_size == entry['size']:
            dst.parent.mkdir(parents=True, exist_ok=True)
            # Separate copy so downloads/verification cannot modify the user's assets.
            shutil.copyfile(src, dst)
            copied += 1
print(f'Reused {copied} existing local asset files; no account data accessed.')

