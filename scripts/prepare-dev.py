"""Prepare a pinned, isolated SkyCraft dev backend. No account/launcher tokens read."""
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / '.runtime' / 'SkyCraft'
COMMIT = 'bfcaf178524b92c2cdeb88e4ce0f13ef9ded6f32'

if not SOURCE.exists():
    subprocess.run(['git', 'clone', 'https://github.com/chasmlol/SkyCraft.git', str(SOURCE)], check=True)
    subprocess.run(['git', '-C', str(SOURCE), 'checkout', '--detach', COMMIT], check=True)
actual = subprocess.check_output(['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], text=True).strip()
if actual != COMMIT:
    raise SystemExit('Unexpected SkyCraft revision; refusing to patch it.')

# Remove automatic social presence and unsolicited network sharing dependencies.
client = SOURCE / 'fabric/src/client/java/dev/skycraft/client/SkyClient.java'
code = client.read_text(encoding='utf-8')
code = code.replace('DiscordPresence.tick(minecraft);', '// MaxCraft: no automatic Discord presence.')
client.write_text(code, encoding='utf-8')
build = SOURCE / 'fabric/build.gradle'
code = build.read_text(encoding='utf-8')
code = code.replace('runtimeOnly "maven.modrinth:e4mc:AouleFRY"', '// MaxCraft: LAN tunnel dependency omitted.')
build.write_text(code, encoding='utf-8')
game = ROOT / '.runtime/minecraft'
game.mkdir(parents=True, exist_ok=True)
options = game / 'options.txt'
if not options.exists():
    options.write_text('bobView:false\nfov:0.0\nguiScale:2\nrenderDistance:6\nsimulationDistance:5\nmaxFps:60\nenableVsync:false\nsoundCategory_music:0.0\n', encoding='utf-8')
shutil.copyfile(SOURCE / 'LICENSE', ROOT / 'THIRD-PARTY-SKYCRAFT-LICENSE.txt')
print(f'Prepared SkyCraft {COMMIT} in {SOURCE}')

