"""Prepare a pinned, isolated SkyCraft dev backend. No account/launcher tokens read."""
from pathlib import Path
import shutil
import subprocess
import sys
import hashlib

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / '.runtime' / 'SkyCraft'
COMMIT = 'bfcaf178524b92c2cdeb88e4ce0f13ef9ded6f32'

if not SOURCE.exists():
    subprocess.run(['git', 'clone', 'https://github.com/chasmlol/SkyCraft.git', str(SOURCE)], check=True)
    subprocess.run(['git', '-C', str(SOURCE), 'checkout', '--detach', COMMIT], check=True)
actual = subprocess.check_output(['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], text=True).strip()
if actual != COMMIT:
    raise SystemExit('Unexpected SkyCraft revision; refusing to patch it.')
properties = SOURCE / 'fabric/gradle.properties'
properties.write_text(properties.read_text(encoding='utf-8').replace('loom_version=1.18-SNAPSHOT', 'loom_version=1.18.4'), encoding='utf-8')

# Remove automatic social presence and unsolicited network sharing dependencies.
client = SOURCE / 'fabric/src/client/java/dev/skycraft/client/SkyClient.java'
code = client.read_text(encoding='utf-8')
code = code.replace('DiscordPresence.tick(minecraft);', '// MaxCraft: no automatic Discord presence.')
stop_hook = '''// MaxCraft: explicit host disconnect requests a normal save-and-quit.
        if (Boolean.getBoolean("maxcraft.quitOnDisconnect") && tookOver && SkyLink.segment() != null
                && SkyLink.segment().get(java.lang.foreign.ValueLayout.JAVA_LONG, 0x10L) == 0L) {
            Minecraft.getInstance().stop();
            return;
        }
        quitWithSkyrim(Minecraft.getInstance());'''
if '// MaxCraft: explicit host disconnect' not in code:
    code = code.replace('quitWithSkyrim(Minecraft.getInstance());', stop_hook)
code = code.replace('Thread.onSpinWait();',
                    'java.util.concurrent.locks.LockSupport.parkNanos(250_000L); // MaxCraft: yield CPU while waiting for Max.')
code = code.replace('options.framerateLimit().set(260);','options.framerateLimit().set(60);')
client.write_text(code, encoding='utf-8')
entrypoint = SOURCE / 'fabric/src/client/java/dev/skycraft/client/SkyCraftClient.java'
code = entrypoint.read_text(encoding='utf-8').replace('DiscordPresence.start();', '// MaxCraft: Discord IPC is disabled.')
entrypoint.write_text(code, encoding='utf-8')
mirror = SOURCE / 'fabric/src/client/java/dev/skycraft/client/MirrorWorld.java'
code = mirror.read_text(encoding='utf-8').replace('GameType.SURVIVAL,', 'GameType.CREATIVE,')
mirror.write_text(code, encoding='utf-8')
build = SOURCE / 'fabric/build.gradle'
code = build.read_text(encoding='utf-8')
code = code.replace('runtimeOnly "maven.modrinth:e4mc:AouleFRY"', '// MaxCraft: LAN tunnel dependency omitted.')
build.write_text(code, encoding='utf-8')

# Max's Qt/Nitrous host does not use Skyrim's frame pacing. The upstream 260 FPS
# override otherwise renders/copies HUD frames that Max can never present.
limiter = SOURCE / 'fabric/src/client/java/dev/skycraft/client/mixin/FramerateLimitTrackerMixin.java'
code = limiter.read_text(encoding='utf-8')
code = code.replace('cir.setReturnValue(260);',
                    'cir.setReturnValue(Math.clamp(Integer.getInteger("maxcraft.backendFps", 60), 30, 120));')
limiter.write_text(code, encoding='utf-8')
gradle_zip = ROOT / '.runtime/gradle-9.7.1-bin.zip'
if gradle_zip.exists():
    expected = 'acd53f1edaf02f1a8ff99879f8a34b302661a057d9b063ae9e35b552f804d20a'
    if hashlib.sha256(gradle_zip.read_bytes()).hexdigest() == expected:
        wrapper = SOURCE / 'fabric/gradle/wrapper/gradle-wrapper.properties'
        text = wrapper.read_text(encoding='utf-8')
        import re
        text = re.sub(r'^distributionUrl=.*$', lambda m: 'distributionUrl=' + gradle_zip.as_uri().replace(':', '\\:'), text, flags=re.M)
        wrapper.write_text(text, encoding='utf-8')
game = ROOT / '.runtime/minecraft'
game.mkdir(parents=True, exist_ok=True)
options = game / 'options.txt'
if not options.exists():
    options.write_text('bobView:false\nfov:0.0\nguiScale:2\nrenderDistance:6\nsimulationDistance:5\nmaxFps:60\nenableVsync:false\nsoundCategory_music:0.0\n', encoding='utf-8')
shutil.copyfile(SOURCE / 'LICENSE', ROOT / 'THIRD-PARTY-SKYCRAFT-LICENSE.txt')
print(f'Prepared SkyCraft {COMMIT} in {SOURCE}')

