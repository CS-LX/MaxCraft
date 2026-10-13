# 验证记录

## 阶段 1：协议及宿主基础（2026-10-13）

- `python -m unittest discover -s tests -v`：11 项通过。覆盖缓冲区满载、回绕、损坏数据、原子交换、坐标变换、碰撞体素和数据布局。
- MSVC x64 编译 `native/atomics.c` 成功。跨进程原子操作使用 Windows Interlocked API。
- Max 2027.2 / Python 3.13.9 / PySide6 6.8.3：实际加载面板成功。
- 在 Max 中创建 9 个演示模型，导出 672 个三角面；后台生成碰撞数据并写入共享内存成功。
- Max 原生材质/网格/UV 冒烟测试通过，临时测试网格已删除。
- Minecraft 真实端到端验证尚待后续阶段，不由以上测试替代。

