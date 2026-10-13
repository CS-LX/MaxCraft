# 调研与实施记录

调研日期：2026-10-13。

## 参考项目

- [SkyCraft](https://github.com/chasmlol/SkyCraft)，MIT，研究源码提交 `bfcaf178524b92c2cdeb88e4ce0f13ef9ded6f32`，发布版 v0.1.2（2026-10-01）。Minecraft 与宿主双进程；共享内存传送碰撞、输入、相机、三缓冲 RGBA 界面、区块和实体网格。使用其现有 Fabric 端。
- [Minecraft X Games](https://github.com/Keel62155/Minecraft-X-Games)：RedCraft、PeakCraft、ReadyCraft，同样复用 SkyCraft Minecraft 端，证明可替换宿主适配器。未复制其代码。
- [HalfCraft](https://github.com/sogutemir/HalfCraft)：GoldSrc/Fabric 方向，进一步参考宿主与原版逻辑分离。未复制其代码。

## Autodesk 官方开发资料

- [2027 Developer Help](https://help.autodesk.com/view/MAXDEV/2027/ENU/)：C++ SDK 用于底层插件；Python/pymxs 用于工具与场景访问。
- [Creating Python UIs](https://help.autodesk.com/cloudhelp/2027/ENU/MAXDEV-Python/files/MAXDEV_Python_creating_python_uis_html.html)：PySide6、主窗口 parenting、qtmax docking。
- [UI tutorial](https://help.autodesk.com/cloudhelp/2026/ENU/MAXDEV-Python/files/tutorials/MAXDEV_Python_tutorials_creating_the_dialog_html.html)：Python 包结构、pymxs 网格创建、调试。
- [Nitrous display interface](https://help.autodesk.com/cloudhelp/2025/ENU/MAXDEV-Developer/files/3ds_max_sdk_features/viewports_and_graphics_windows/nitrous/plug-in_display_interface.html)：C++ IObjectDisplay2 与 retained render items。当前先使用原生场景网格，后续性能瓶颈可转为 C++。
- [QtHelpers](https://help.autodesk.com/cloudhelp/2027/ENU/MAXDEV-CPP-API-REF/namespace_qt_helpers.html)：游戏控件获得焦点时关闭 Max 快捷键，失焦恢复。

## 本机实测环境

- Max：`D:/Development Programs/AutoDesk/3ds Max 2027/3dsmax.exe`，初始场景为空。
- 自带 Python 3.13.9，PySide6 可用；不依赖用户 Python 环境安装第三方包。
- 已有 Minecraft 26.3 本地版本。不会读取或提交账号令牌。
- 用户明确要求永久关闭 MCP safe_mode；配置已写为 false，当前 Max 的原生桥接缓存需要重新启动才能生效。

## 实施阶段与验收

1. 调研、仓库、坐标/协议适配：协议布局、环缓冲边界、碰撞/坐标转换自动测试通过。
2. Max 插件：安装入口、控制面板、场景碰撞、相机、方块网格、原版 HUD、键鼠输入、暂停及恢复。
3. 真正 Minecraft 接入：隔离游戏目录；复用 SkyCraft Fabric；实机握手、站立/移动/跳跃、挖放方块、背包交互。
4. 交付：打包、中文说明、已验证功能与限制，提交代码后完成目标。

明确限制将依据实测列出；不会把模拟协议测试当作真实 Minecraft 端到端测试。

