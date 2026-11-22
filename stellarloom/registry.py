"""MC 风格物品注册表（M7）：启动时注册，动态分配数字 id。

- **名字**（"stellarloom:iron_ore"）是持久化/交互表示：存档、配方 JSON、
  mod API 都用它。
- **数字 id** 是运行时表示：sim.inventory、机器槽、网格数组、渲染查色
  都走它——**消费方零改动**。
- 原版命名空间固定 `stellarloom:`；mod 用自己目录名作命名空间。
- 兼容两条老路：
  * mod 旧代码 `ctx.add_item(300, ...)` 传数字 → **固定 id 注册**
    （token = "mod名:item300"），旧存档里的数字 300 在分配表里仍查得到。
  * 存档旧档全是数字键 → `id_of("12")` 兜底转数字，同一进程内能反查名字。
- 动态分配从 15 起（原版材料占 1-14、建筑物品占 101-112），跳号不重。
"""

from __future__ import annotations

VANILLA = "stellarloom"
"""原版命名空间（用户钦定）。"""


class RegistryError(Exception):
    """注册/查询冲突（id 或名字被占、查无此物）。"""
    pass


class ItemRegistry:
    def __init__(self):
        self._id2name: dict[int, str] = {}
        self._name2id: dict[str, int] = {}
        self._id2disp: dict[int, str] = {}
        self._id2color: dict[int, tuple] = {}
        self._next = 15          # 动态分配起点（原版材料 1-14、建筑物品 101-112）

    # ---------------- 注册 ----------------

    def fixed_register(self, iid: int, name: str, display: str,
                       color=None) -> int:
        """固定 id 注册：原版物品、旧 mod 数字式 add_item（兼容段）。"""
        if not isinstance(iid, int) or iid <= 0:
            raise RegistryError(f"固定 id 必须是正整数，收到 {iid!r}")
        if iid in self._id2name:
            raise RegistryError(
                f"id {iid} 已被 {self._id2name[iid]} 占用")
        if name in self._name2id:
            raise RegistryError(
                f"名字 {name} 已被注册（id {self._name2id[name]}）")
        self._id2name[iid] = name
        self._name2id[name] = iid
        self._id2disp[iid] = display
        if color is not None:
            self._id2color[iid] = color
        return iid

    def dynamic_register(self, name: str, display: str, color=None) -> int:
        """动态分配 id 注册：mod 新式名字注册（M7 推荐）。"""
        if name in self._name2id:
            raise RegistryError(
                f"名字 {name} 已被注册（id {self._name2id[name]}）")
        iid = self._find_free()
        self._id2name[iid] = name
        self._name2id[name] = iid
        self._id2disp[iid] = display
        if color is not None:
            self._id2color[iid] = color
        return iid

    def unregister(self, name: str):
        """卸载 mod 时撤销注册（只清自己注册的）。"""
        iid = self._name2id.pop(name, None)
        if iid is None:
            return
        self._id2name.pop(iid, None)
        self._id2disp.pop(iid, None)
        self._id2color.pop(iid, None)
        # 动态分配段归还给分配器（固定段无所谓，id 本来固定）

    def _find_free(self) -> int:
        while self._next in self._id2name:
            self._next += 1
        iid = self._next
        self._next += 1
        return iid

    # ---------------- 查询（容错优先） ----------------

    def has_name(self, name: str) -> bool:
        return name in self._name2id

    def name_of(self, key) -> str:
        """id / 名字 / 数字字符串 → 全名（"stellarloom:iron_ore"）。
        未知 id 原样返回 str（显示 '?'，与老行为一致）。"""
        if isinstance(key, int) or isinstance(key, float):
            return self._id2name.get(int(key), str(int(key)))
        s = str(key)
        if s.lstrip("-").isdigit():
            return self._id2name.get(int(s), s)
        return s

    def id_of(self, key) -> int:
        """名字 / 数字 / 数字字符串 → id。查不到就抛 RegistryError。"""
        if isinstance(key, int):
            if key not in self._id2name:
                raise RegistryError(f"物品 id {key} 未注册")
            return key
        s = str(key)
        if s.lstrip("-").isdigit():
            i = int(s)
            if i not in self._id2name:
                raise RegistryError(f"物品 id {i} 未注册")
            return i
        if s not in self._name2id:
            raise RegistryError(f"物品 {s!r} 未注册（格式应为 命名空间:名字）")
        return self._name2id[s]

    def display_of(self, key) -> str:
        if isinstance(key, int):
            return self._id2disp.get(key, "?")
        s = str(key)
        if s.lstrip("-").isdigit():
            return self._id2disp.get(int(s), "?")
        i = self._name2id.get(s)
        return self._id2disp.get(i, s) if i is not None else s

    def color_of(self, key, fallback=(200, 200, 200)):
        if isinstance(key, int):
            return self._id2color.get(key, fallback)
        s = str(key)
        if s.lstrip("-").isdigit():
            return self._id2color.get(int(s), fallback)
        i = self._name2id.get(s)
        return self._id2color.get(i, fallback) if i is not None else fallback

    # ---------------- 全量视图（喂给 C.ITEM_NAMES 等老 dict） ----------------

    @property
    def names_map(self) -> dict[int, str]:
        """实时视图（内部引用）：id → 显示名。mod 注册后立即可见。"""
        return self._id2disp

    @property
    def colors_map(self) -> dict[int, tuple]:
        return self._id2color

    @property
    def ids_map(self) -> dict[str, int]:
        """实时视图：名字 → id。"""
        return self._name2id

    def id_to_display(self) -> dict[int, str]:
        return dict(self._id2disp)

    def id_to_color(self) -> dict[int, tuple]:
        return dict(self._id2color)

    def name_to_id(self) -> dict[str, int]:
        return dict(self._name2id)

    def id_to_name(self) -> dict[int, str]:
        return dict(self._id2name)


# 全局单例：config.py 在 import 时填充原版，mod 在加载时注册自己的
ITEM_REGISTRY = ItemRegistry()


class FluidRegistry(ItemRegistry):
    """液体注册表（M14）：id 从 1 起，0 = 空。

    与物品注册表同哲学（名字持久化 / 数字运行时），但**独立段**：
    液体不进背包、不上传送带、不进分拣器过滤列表，所以绝不能和
    物品 id 混用——两边各有一张表，谁也不会踩谁。
    """

    def __init__(self):
        super().__init__()
        self._next = 1        # 液体从 1 起（0 留作"空"）



class BuildingRegistry:
    """建筑类型注册表（M8）：名字 ↔ 数字 id。

    - 原版建筑固定段 1-13（B_BELT..B_EMITTER）。
    - mod 建筑用名字注册（"mymod:foundry"）→ 动态分配从 100 起，避开
      原版 1-13 与存量 mod 硬编码段（重工 20-23、星海 30-37）。
    - 旧式固定注册：add_building(30, ...) 传 int → 键 "mod名:b30"。
    - 建筑类型是"地块类型"：内部 numpy building 数组、存档仍用数字；
      注册表提供名字的标准入口与显示名（与物品注册表同哲学）。
    """

    DYNAMIC_START = 100

    def __init__(self):
        self._id2name: dict[int, str] = {}
        self._name2id: dict[str, int] = {}
        self._id2disp: dict[int, str] = {}
        self._next = self.DYNAMIC_START

    def fixed_register(self, iid: int, name: str, display: str) -> int:
        if not isinstance(iid, int) or iid <= 0:
            raise RegistryError(f"固定建筑 id 必须是正整数，收到 {iid!r}")
        if iid in self._id2name:
            raise RegistryError(
                f"建筑 id {iid} 已被 {self._id2name[iid]} 占用")
        if name in self._name2id:
            raise RegistryError(
                f"建筑名字 {name} 已被注册（id {self._name2id[name]}）")
        self._id2name[iid] = name
        self._name2id[name] = iid
        self._id2disp[iid] = display
        return iid

    def dynamic_register(self, name: str, display: str) -> int:
        if name in self._name2id:
            raise RegistryError(
                f"建筑名字 {name} 已被注册（id {self._name2id[name]}）")
        while self._next in self._id2name:
            self._next += 1
        iid = self._next
        self._next += 1
        self._id2name[iid] = name
        self._name2id[name] = iid
        self._id2disp[iid] = display
        return iid

    def unregister(self, name: str):
        iid = self._name2id.pop(name, None)
        if iid is None:
            return
        self._id2name.pop(iid, None)
        self._id2disp.pop(iid, None)

    def has_name(self, name: str) -> bool:
        return name in self._name2id

    def name_of(self, key) -> str:
        if isinstance(key, int) or isinstance(key, float):
            return self._id2name.get(int(key), str(int(key)))
        s = str(key)
        if s.lstrip("-").isdigit():
            return self._id2name.get(int(s), s)
        return s

    def id_of(self, key) -> int:
        if isinstance(key, int):
            if key not in self._id2name:
                raise RegistryError(f"建筑 id {key} 未注册")
            return key
        s = str(key)
        if s.lstrip("-").isdigit():
            i = int(s)
            if i not in self._id2name:
                raise RegistryError(f"建筑 id {i} 未注册")
            return i
        if s not in self._name2id:
            raise RegistryError(
                f"建筑 {s!r} 未注册（格式应为 命名空间:名字）")
        return self._name2id[s]

    def display_of(self, key) -> str:
        if isinstance(key, int):
            return self._id2disp.get(key, "?")
        s = str(key)
        if s.lstrip("-").isdigit():
            return self._id2disp.get(int(s), "?")
        i = self._name2id.get(s)
        return self._id2disp.get(i, s) if i is not None else s

    @property
    def names_map(self) -> dict[int, str]:
        """实时视图：建筑 id → 显示名（BUILDING_NAMES 同源引用）。"""
        return self._id2disp

    def id_to_name(self) -> dict[int, str]:
        return dict(self._id2name)

    def name_to_id(self) -> dict[str, int]:
        return dict(self._name2id)


BUILDING_REGISTRY = BuildingRegistry()

# 液体注册表单例（M14）：config.py 注册原版三种，mod 用 ctx.add_fluid 加自己的
FLUID_REGISTRY = FluidRegistry()