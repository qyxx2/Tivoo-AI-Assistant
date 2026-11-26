# Tivoo Rotating Base CAD

Tivoo AI Assistant 的可旋转底座参数化 CAD 工程。当前版本用于确定外观比例、旋转圆盘尺寸和内部器件布局，并作为后续机械结构、齿轮、轴承/转盘、滑环、走线与 3D 打印拆件设计的基线。

> **当前状态：V1 概念与布局阶段，不是可直接打印的最终机械件。**
>
> 当前模型已经确定整体设计方向和主要空间包络，但 Tivoo 四脚位置、内部板卡包络、舵机/齿轮、滑环等仍需要在最终结构设计前按实物复测。不要把 proxy/envelope 尺寸当成厂家机械图尺寸。

## 当前设计方向

- 底座外形跟随 Tivoo 本体的圆角矩形比例，不采用割裂的方盒造型。
- 当前总体包络约为 **136 × 114 × 29 mm**。
- 顶部中心旋转圆盘当前直径约 **108 mm**，用于容纳 Tivoo 四个脚并尽量控制底座长宽。
- 中心预留小型滑环位置，使 Tivoo/旋转部分能够连续转动而不扭线。
- V1 布局使用概念性的 **2:1 齿轮减速（50T : 25T，module 1）** 和 FS90R 级连续旋转微型舵机包络。
- 内部同时预留 ESP32-S3、Classic ESP32、PCM5102、电源分配/降压、舵机电容和前沿麦克风板空间。
- 当前麦克风布局模型包含 2 × INMP441 与 3 × ICS43434 的位置包络，主要用于判断底座前沿空间和阵列长度。

这些数值是当前参数化模型的设计基线，不代表全部已通过实体打印和装配验证。

## 目录

```text
tivoo-rotating-base/
├── README.md
├── preview.png
├── previews/
│   ├── external_v1_iso.png
│   ├── external_v1_top.png
│   ├── layout_v1_iso.png
│   └── layout_v1_top.png
└── src/
    ├── base.py
    ├── external_v1.py
    └── layout_v1.py
```

### `src/base.py`

最早的圆角矩形底座参数化试验，用于验证 build123d/Text-to-CAD 参数化建模和 3D Viewer 工作流。

当前默认值：

- length: 120 mm
- width: 110 mm
- height: 8 mm
- corner_radius: 12 mm

它不是当前旋转底座的主要设计文件。

### `src/external_v1.py`

外观比例模型。主要用于判断：

- 底座与 Tivoo 本体的比例是否协调；
- 圆角矩形与圆形旋转盘的视觉关系；
- 底座高度是否显得过厚；
- 108 mm 旋转盘与 Tivoo 四脚的大致关系。

其中 Tivoo 本体使用 **100 × 83 × 83 mm** 的外形 proxy。四脚位置是根据产品照片做的视觉估算，代码中已经明确标记为非厂家尺寸。

### `src/layout_v1.py`

V1 内部空间布局模型，是目前最重要的 CAD 源文件。包含：

- 3 mm 底板和 3 mm 壁厚的圆角外壳；
- 108 mm 顶部旋转圆盘；
- 12.5 × 18.2 mm 小型滑环包络；
- 50T / 25T 概念齿轮包络；
- FS90R 级舵机包络；
- ESP32-S3 与 Classic ESP32 载板/开发板包络；
- PCM5102 模块；
- USB-C 电源分配/降压空间；
- 1000–2200 µF 级舵机支路电容空间；
- 5 个前沿麦克风模块包络；
- Tivoo 四脚 keep-out proxy。

## 参数化修改

主要外观参数都集中在源文件开头，并通过当前 Text-to-CAD 的 `model.param(...)` 暴露，例如：

```python
BASE_L = model.param("base_length", 136.0, ...)
BASE_W = model.param("base_width", 114.0, ...)
BASE_H = model.param("base_height", 29.0, ...)
CORNER_R = model.param("corner_radius", 25.0, ...)
PLATTER_D = model.param("platter_diameter", 108.0, ...)
```

后续优先继续保持参数化，而不是把关键尺寸散落成硬编码实体。外壳、旋转盘、器件位置发生变化时，应同步更新预览图和本文档中的设计基线。

## 当前预览

- `preview.png`：当前默认预览。
- `previews/external_v1_iso.png`：外观 V1 等轴视图。
- `previews/external_v1_top.png`：外观 V1 顶视图。
- `previews/layout_v1_iso.png`：内部布局 V1 等轴视图。
- `previews/layout_v1_top.png`：内部布局 V1 顶视图。

预览图用于快速比较方案，不应作为尺寸标注图。

## 尚未定稿的机械部分

以下内容当前只做到概念或空间预留，后续真正进入打印前需要继续建模：

- Tivoo 四脚的实测中心距、脚径和脚高，以及对应限位/防滑结构。
- 旋转圆盘与固定底座之间的真实支撑方式：轴承、转盘轴、滚珠或其它低摩擦结构。
- 圆盘轴向/径向限位与装配方式。
- 真实齿形、中心距、公差、舵机固定座和齿轮防脱结构。
- 滑环的固定、应力释放、走线和旋转部分连接。
- 电路板固定柱、螺丝孔、USB/音频/调试接口开口。
- 麦克风声孔、模块固定方式以及避免壳体遮挡/腔体共振的结构。
- 上下壳拆装、螺丝/卡扣、打印方向和公差。
- 最终 STL/STEP 等制造输出。

## 版本管理

CAD 工程与 Tivoo-AI-Assistant 主仓库一起由 Git 管理，不单独建立另一个仓库。

修改原则：

1. 参数、器件布局和外观草案直接在本目录迭代。
2. 明确可比较的方案保留独立源文件或版本名，例如 `layout_v2.py`，不要覆盖掉有价值的结构分支。
3. 预览图与对应源文件一起提交。
4. 真正进入可打印结构后，再增加明确的 manufacturing/export 目录和最终制造文件。
5. 当前 V1 属于项目历史基线；后续机械设计可以在独立 feature 分支迭代，再合并回主项目。
