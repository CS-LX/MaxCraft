"""Execute inside Max. Install only MaxCraft's own scripts and named macro."""
from pathlib import Path
import shutil
import json
from pymxs import runtime as rt

source = Path(__file__).resolve().parent
if not (source / 'maxcraft/_native/atomics.dll').is_file():
    raise RuntimeError('缺少 atomics.dll，请先运行 scripts/build_native.cmd，或使用发布安装包。')
target = Path(str(rt.getDir(rt.Name('userScripts')))) / 'MaxCraft'
target.mkdir(parents=True, exist_ok=True)
shutil.copytree(source / 'maxcraft', target / 'maxcraft', dirs_exist_ok=True,
                ignore=shutil.ignore_patterns('__pycache__', '*.obj', '*.lib', '*.exp'))
shutil.copy2(source / 'launch_maxcraft.py', target / 'launch_maxcraft.py')
(target / 'maxcraft/installation.json').write_text(json.dumps({'project_root':str(source)}, ensure_ascii=False), encoding='utf-8')
launch = (target / 'launch_maxcraft.py').as_posix()
macro = Path(str(rt.getDir(rt.Name('userMacros')))) / 'MaxCraft-Play.mcr'
macro.write_text('macroScript MaxCraft_Play category:"MaxCraft" toolTip:"Minecraft inside 3ds Max" buttonText:"MaxCraft"\n'
                 '(\n    on execute do python.ExecuteFile @"' + launch + '"\n)\n', encoding='utf-8')
rt.fileIn(str(macro))
print(f'MaxCraft installed: {target}\nAction: MaxCraft > MaxCraft_Play')

