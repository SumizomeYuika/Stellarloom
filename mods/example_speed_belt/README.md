# 示例 mod：超速传送带 ×2

复制 `mods/example_speed_belt/` 目录改名即得自己的 mod。
加载/卸载效果：启动时 Game 自动扫描并加载 `mods/*/`；游戏内提示
"示例 mod：传送带 ×2 已启用"（on_load 的 ctx.toast）。删掉这个目录或
把 main.py 改名即可让传送带还原原速。

## 这 8 行代码展示了什么

```python
def on_load(ctx):
    ctx.toast("示例 mod：传送带 ×2 已启用", 2.0)          # 1. 游戏内提示
    def double_speed(self, dt):
        return ((dt * 2.0,), {})                          # 2. before 返回 (args, kwargs)
    ctx.mixin("stellarloom.logistics.belts.BeltNetwork",  # 3. mixin 目标 = 点分路径
              "update", double_speed, wrap="before")
def on_unload(ctx):                                       # 4. 卸载钩子（可选）
```

- **wrap="before"**：原方法（`BeltNetwork.update`）前跑；返回
  `(args, kwargs)` 即替换调用参数——这里把 `dt` 翻倍，传送带整体 ×2 速。
  返回 `None` 则不干预。这是 before 最常见的两种用法之一。
- **非永久**：mixin 只动内存；卸载/重载时加载器自动还原原方法，
  源码（`stellarloom/logistics/belts.py`）一个字没改。
- 完整 API 见 `Docs/Mods.md`。