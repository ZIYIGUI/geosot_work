# GeoSOT 网格引擎复现（iwhereGIS 兼容 · GB/T 40087-2021 符合）

基于 `GeoSOT-iwhere-openapi.yaml`（80 个接口路径）在本地以纯 Python 复现的
GeoSOT 地球空间网格编码引擎。编码核心为零依赖的标准库实现，几何服务与
HTTP 层使用 FastAPI，测试既覆盖与 iwhere 黄金响应的逐字段比对，也覆盖
国家标准 GB/T 40087-2021 的官方编码示例与非 HTTP 单元测试。

---

## 📑 目录导航

- [一、目录结构](#一目录结构)
- [二、快速开始](#二快速开始)
- [三、与 iwhereGIS GeoSOT 引擎的对应关系](#三与-iwheregis-geosot-引擎的对应关系)
- [四、符合 GB/T 40087-2021《地球空间网格编码规则》](#四符合-gbt-40087-2021地球空间网格编码规则)
- [五、测试结果展示](#五测试结果展示)
- [六、数据文件编码（无人机轨迹 / 空间封闭区域）](#六数据文件编码无人机轨迹--空间封闭区域)
- [七、坐标 -> HTTP 格式 JSON（非单元测试）](#七坐标---http-格式-json非单元测试)
- [八、与 GB/T 40087 的一致性说明](#八与-gbt-40087-的一致性说明)
- [九、复现说明](#九复现说明)
- [十、无人机轨迹冲突检测与 PSI 计算](#十无人机轨迹冲突检测与-psi-计算)
- [十一、空域网格计算（无人机低空导航）](#十一空域网格计算无人机低空导航)
- [十二、空域可用性计算（城市低空监管）](#十二空域可用性计算城市低空监管)
- [十三、CPSI 交集基数计算](#十三cpsi-交集基数计算)

---

## 一、目录结构

```
geosot_work/
├── src/                 # 源代码目录
│   ├── geosot_core.py       # 编码核心库: 路线A/B、行列、子/父/邻域、3D、进制、距离、128位/16字节、GB附录D辅助
│   ├── geosot_service.py    # 几何服务层: 点/线/面/矩形/缓冲/聚合/外接矩形/路径/视频模型等
│   ├── app.py               # FastAPI 应用: 80 个接口 handler（与 YAML 路径一一对应）
│   ├── geofile.py           # 地理信息文件读取与编码映射: GeoJSON/SHP/CSV/WKT/KML/GPX
│   ├── test_all.py          # HTTP 黄金比对: 逐字段比对 geosot_examples.json（PASS/DIFF/FAIL/INFO/SKIP）
│   └── restart_and_test.py  # 一键重启 uvicorn 服务并运行全量黄金回归
│
├── data/                # 输入: 示例地理数据（无人机轨迹点 + 空间封闭区域）
│   ├── uav_track.geojson        # 无人机飞行轨迹 (2 架次 LineString, 各 10 航点)
│   ├── uav_points.csv           # 无人机轨迹航点表 (lon/lat/alt/时间/机号, 10 点)
│   ├── uav_track3d.csv          # 3D 航线数据 (lon/lat/alt_m/时间/机号, 10 航点, 96 位 3D 码)
│   ├── closed_area.geojson      # 空间封闭区域 (2 个禁飞区 Polygon, 闭合环)
│   ├── uav_conflict_1.csv       # 冲突轨迹1 (10000 航点, 用于 PSI 测试)
│   └── uav_conflict_2.csv       # 冲突轨迹2 (10000 航点, 与轨迹1约5100个冲突点)
│
├── out/                 # 输出: 编码提取产物
│   ├── codes.json            # 全部提取编码 (类型/码/层级/维度/128位/16字节hex/属性)
│   ├── codes_128.bin         # 每条 16 字节(128 位) 大端连续写入 (2D 低 8 字节, 3D 低 12 字节)
│   ├── codes_16bytes.csv     # CSV 仅一列 bytes16_hex, 与 bin 逐条对应
│   ├── http_like_response.json  # 坐标 -> HTTP 格式 JSON 响应（19 接口, 全部 status:200）
│   ├── conflict_codes_128.bin   # 轨迹冲突检测的交集编码 (128位二进制)
│   ├── trajectory_party1.bin    # PSI 输入: 轨迹1编码
│   ├── trajectory_party2.bin    # PSI 输入: 轨迹2编码
│   ├── psi_result_party1.bin    # PSI 输出: 交集结果 (二进制)
│   ├── psi_out.bin              # PSI 单独执行的输出
│   ├── airspace_grids.bin       # 空域网格编码 (3D 码, 约100万个)
│   └── airspace_availability/   # 空域可用性计算产物
│       ├── available_grids_Y.bin    # 可用网格集合 Y (150646 × 16)
│       ├── query_airspace_X.bin     # 查询空域网格 X (7920 × 16)
│       ├── plaintext_intersection.bin # 明文交集 (5940 × 16)
│       └── psi_intersection.bin     # PSI 交集 (5940 × 16)
│
├── tests/               # 测试套件 (unittest) + 可独立执行的脚本
│   ├── test_gbt40087.py         # GB/T 40087 附录 D/A/B 标准符合性测试
│   ├── test_unit.py             # 核心函数单元测试 + 黄金样例直测
│   ├── test_geofile.py          # 地理信息文件解析与编码映射测试
│   ├── test_data_encode.py      # data/ -> out/ 数据编码流水线测试
│   ├── test_trajectory_conflict.py  # 无人机轨迹冲突检测 (编码 + 集合交集)
│   ├── test_psi_trajectory.py   # 无人机轨迹 PSI 计算 (调用 psi/frontend.exe)
│   ├── test_airspace_grids.py   # 空域网格计算 (德清县区域, 约100万网格)
│   ├── test_airspace_availability.py  # 空域可用性计算 (城市低空监管, PSI 对比)
│   ├── test_cpsi_cardinality.py       # CPSI 交集基数计算 (仅返回交集大小)
│   ├── gen_large_trajectories.py    # 生成大规模轨迹数据 (10000 航点)
│   ├── encode_data.py           # 数据编码脚本: data/ -> 网格编码提取 -> out/
│   └── coords_to_json.py        # 坐标 -> 与 HTTP 返回格式一致的 JSON
│
├── psi/                 # PSI (隐私集合交集) 工具
│   └── frontend.exe           # PSI 可执行文件
│
├── geosot_examples.json       # iwhere 黄金响应（src/test_all.py / tests/test_unit.py 读取）
├── GeoSOT-iwhere-openapi.yaml # 接口定义（80 个路径, src/test_all.py 读取）
├── paths.json                 # 接口路径列表
├── schemas.json               # 接口 schema 定义
├── std_text.txt               # 标准文本参考
└── manual_text.txt            # 手动整理文本

测试套件运行:  python -m unittest discover -s tests -v
```

## 二、快速开始

环境: Python 3.14（`D:\pyenv\pyenv-win\versions\3.14.5\python.exe`）,
依赖 `fastapi`、`uvicorn`、`numpy`（仅视频模型）、`pypdf`（读标准 PDF）。

```powershell
# 1. 启动 HTTP 服务（默认 127.0.0.1:8000）
cd src && python -m uvicorn app:app --host 127.0.0.1 --port 8000
# 或一键重启 + 回归:
python src\restart_and_test.py

# 2. 全量黄金比对（80 路径, 逐字段）
python src\test_all.py

# 3. 非 HTTP 测试套件（GB/T 40087 示例 + 单元测试 + 文件解析）
python -m unittest discover -s tests -v

# 4. 地理信息文件 -> 网格编码（CLI）
python src\geofile.py input.geojson --level 15 --route B --out result.json
python src\geofile.py input.shp --level 20 --route B

# 5. data/ 示例数据 -> 网格编码提取 -> out/（默认 21 级, 1" 网格）
python tests\encode_data.py --level 21 --route B

# 6. 非单元测试: 输入坐标 -> 与 HTTP 返回格式一致的 JSON（无需启动服务）
python tests\coords_to_json.py --lat 39.9102778 --lng 116.3152778 --height 500 --level 21
```

> `tests/encode_data.py` 与 `tests/coords_to_json.py` 既是测试套件的组成脚本，
> 也可独立执行（输出固定写入项目根 `out/`）。二者的路径自动解析到项目根，
> 从任何工作目录运行均可。

## 三、与 iwhereGIS GeoSOT 引擎的对应关系

`app.py` 中 80 个接口路径与 `GeoSOT-iwhere-openapi.yaml` 一一对应，请求/响应
字段名与 YAML schema 完全一致，响应体结构与黄金响应逐字段可比。主要分组:

| 分组 | 路径示例 | 说明 |
|------|----------|------|
| 编码/解码 | `/geosot/point`、`/geosot/row_col2geo_num`、`/geosot/geo_num2row_col` | 路线B编码、行列互转 |
| 层级 | `/geosot/child_geo_num`、`/geosot/parent_geo_num`、`/geosot/scope_geo_num` | 子网格、父网格、作用域 |
| 邻域 | `/geosot/adjoin4_geo_num`、`/geosot/adjoin8_geo_num`、`/geosot/adjoin_azimuth_geo_num` | 4/8 邻域与方位 |
| 几何服务 | `/geosot/line`、`/geosot/polygon`、`/geosot/rect`、`/geosot/point_buffer` 等 | 线/面/矩形/缓冲网格化 |
| 集合运算 | `/geosot/overlay_analysis_union`、`intersection`、`/geosot/sort_*`、`/geosot/traversal_geo_num` | 并交、排序、遍历 |
| 度量 | `/geosot/area_geo_num`、`/geosot/sphere_distance_geo_num`、`/geosot/azimuth_geo_num` | 面积、球面距离、方位 |
| 北斗 | `/geosot/beidou_grid_code2geo_num`、`/geosot/geo_num2beidou_grid_code` | 北斗网格码互转 |
| 3D | `/geosot3d/point3d`、`/geosot3d/adjoin6_geo_num`、`/geosot3d/adjoin26_geo_num`、`/geosot3d/cylinder` 等 | 3D 编码/邻域/体元 |
| 视频模型 | `/geosot/video_model` | 相机外参 DLT 求解与像素映射 |
| 文件映射 | `geofile.py` CLI | 地理信息文件读取 + 编码（非 HTTP） |

### 编码路线对应

- **路线 A**（`geo_num_routeA`）: `morton(pack_dms(lat), pack_dms(lng), 31)`，
  `pack_dms = (deg<<23)|(min<<17)|(sec<<11)|subsec`（度9/分6/秒6/亚秒11），
  对应引擎 routeA 的 DMS 十进制码，23 级精度。
- **路线 B**（`geo_num_routeB`）: `morton(r, c, level) << (64 - 2*level)`，
  连续网格码，行列号 `r/c` 由 `row_col(lat, lng, level)` 得出（1°=64 扩展分）。
- **3D 编码**: `interleave3(lat, lng, h, order=(2,0,1), nbits=32)`，96 位，
  h 维按 GB/T 40087 附录 B 高度域剖分（不等距），`h = 层号×2 + 子位`。

## 四、符合 GB/T 40087-2021《地球空间网格编码规则》

本项目按国家标准实现核心编码规则，并在 `tests/test_gbt40087.py` 中
用标准原文给出的示例逐位验证:

| 标准章节 | 验证内容 | 测试 |
|----------|----------|------|
| 附录 D 表 D.1 | 北京世纪坛中心 (39°54′37.0″N, 116°18′54.8″E) 经纬度度分秒→分段二进制（度9位/分6位/秒6位/秒小数12位） | `gb_dms_binary` 逐位断言 |
| 附录 D b)/c) | 4° 级莫顿交叉 `00000111010011` → 四进制代码 `G0013103`；2° 级 → `G00131032` | `gb_deg_grid_morton` + `gb_quaternary` |
| 附录 D a) | 4°/2°/1° 级经纬度网格编码截断 | 二进制前缀断言 |
| 附录 A 表 A.1 | 0–32 级单元跨度（512°…1/2048″）与赤道尺度 | `cell_deg` / `R0·θ0·cell_deg` |
| 附录 B | 高度域公式 (B.3)–(B.7)：`H_{255}=519501834.1582395m`、`r_{255}=525879971.1582395m`、`H_{-256}=-6302106.722602182m`、`H_{256}=528680171.1252437m` | 与标准特征值比对（<0.01m） |
| 5.6/6.3 | 高度域剖分与高度域编码 | `height_cell` / `height_index` 与附录 B 档位互推 |

> 附录 D 破译要点: 4° 级莫顿为 `morton(39//4=9, 116//4=29, 7)` = 467 =
> 14 位二进制 `00000111010011`（纬度前置、经度后置交叉）; 四进制代码 =
> 莫顿二进制每 2 位一组 + 半球号 `G` 前缀，宽度按 14 位（4° 级 7 对）展开。

## 五、测试结果展示

### 5.1 全量黄金比对（HTTP, 80 路径）

```
==== 结果: PASS=64 DIFF=0 FAIL=0 INFO=2 (跳过 4) ====
[PASS] /geosot/point                    geo_num=1188950301625810944-5
[PASS] /geosot/center_point             coordinates:全等✓(2项)
[PASS] /geosot/beidou_grid_code2geo_num geo_num=412869894958481400✓ | geo_level=23✓
[PASS] /geosot/rect                     geo_num_list:全等✓(225项)
[PASS] /geosot/polygon_buffer           geo_num_list:全等✓(44项)
[PASS] /geosot/overlay_analysis_union   geo_num_list:全等✓(12项)
[PASS] /geosot/video_model              geo_num_list:全等✓(1项) | pixel_trans_matrix:全等✓(9项)
[PASS] /geosot3d/adjoin26_geo_num       geo_num_list:全等✓(26项)
[PASS] /geosot3d/relative_azimuth       azimuth=1.5707963267948966✓
[INFO] /geosot/aggregation_geo_num      聚合口径: 黄金为 routeA 跨层父码, 本地按 routeB 目标层映射
[INFO] /geosot/line_buffer              YAML 请求无 lats/lngs 示例, 测试无法构造坐标参数
```
（4 个 SKIP: geojson/multi_line/multi_polygon/multi_point，YAML 无黄金示例。）

### 5.2 非 HTTP 测试套件（103 用例全过）

```
$ python -m unittest discover -s tests -v
Ran 103 tests in 10.1s
OK
```
关键断言示例:
- `gb_dms_binary(39,54,37,0.0) == '000100111 110110 100101.000000000000'`
- `gb_quaternary('00000111010011') == 'G0013103'`（附录 D c)）
- `H_{255}` 公式值与标准 519501834.1582395m 一致
- 128 位二进制 / 16 字节（大端）往返无损（2D 64 位 / 3D 96 位）
- 黄金直测: `beidou2geo_num('N48H67171CA372') == 412869894958481400`
- `line_cells` / `polygon_cells` / `rect_cells` 几何服务自洽
- data/ -> out/ 数据编码流水线: 提取 1983 条码（含 10 条 3D 航线）, bin 大小 = 16×N, bin/csv 往返还原一致

### 5.3 文件编码映射示例

```powershell
$ python geofile.py %TEMP%\t.geojson --level 15 --route B
格式=geojson 层级=15 路线=B 编码数=1
  Point       526549933789020160-15
```
输出 JSON 每条要素含 `code`（`码-层级`）、`binary128`（128 位二进制）、
`bytes16_hex`（16 字节大端 hex）、`props`（属性）。

## 六、数据文件编码（无人机轨迹 / 空间封闭区域）

`data/` 提供两类示例数据，`tests/encode_data.py` 统一读取并映射为 GeoSOT 网格编码，
产物写入 `out/`。

### 6.1 输入数据

| 文件 | 内容 | 几何类型 |
|------|------|----------|
| `data/uav_track.geojson` | 无人机飞行轨迹，2 架次各 10 个航点（含机号/任务/高度/速度属性） | LineString |
| `data/uav_points.csv` | 轨迹航点表（lon/lat/高度/时间/机号，10 行） | Point |
| `data/uav_track3d.csv` | 3D 航线数据（lon/lat/高度/时间/机号，10 航点，高度 100→300→100 m 爬升-巡航-下降） | Point3D |
| `data/closed_area.geojson` | 空间封闭区域，2 个临时禁飞区（闭合环，含名称/类型/限高属性） | Polygon |

#### 样例数据摘录（真实文件内容）

`data/uav_points.csv`（表头 + 前 3 行）:
```
lon,lat,alt_m,time_s,drone_id
116.3150,39.9100,120,0,DJI-M300-01
116.3170,39.9115,121,15,DJI-M300-01
116.3190,39.9125,119,30,DJI-M300-01
```

`data/uav_track3d.csv`（3D 航线，表头 + 前 3 行，高度 100→150→200 m 爬升段）:
```
lon,lat,alt_m,time_s,drone_id
116.3000,39.9000,100,0,DJI-M300-03
116.3030,39.9020,150,10,DJI-M300-03
116.3060,39.9040,200,20,DJI-M300-03
```

`data/uav_track.geojson` / `closed_area.geojson` 结构（FeatureCollection）:
```json
{"type": "Feature", "properties": {"drone_id": "DJI-M300-01", "mission": "航线巡检", "altitude_m": 120, "speed_ms": 8},
 "geometry": {"type": "LineString", "coordinates": [[116.3150, 39.9100], [116.3160, 39.9110], ...]}}
{"type": "Feature", "properties": {"name": "临时禁飞区A", "zone_type": "no-fly", "effective_h": 500},
 "geometry": {"type": "Polygon", "coordinates": [[[lng, lat], ..., [lng, lat]]]}}   // 闭合环
```

### 6.2 提取流程

```
python tests\encode_data.py --level 21 --route B
```
- 默认 21 级（1″ 网格，赤道约 30.9 m，适配无人机尺度），路线 B 连续网格码；
- 2D 文件（不含 `3d` 的文件名）经 `geofile.encode_file` 映射（Point→1 码、LineString/Polygon→覆盖网格集合）；
- 文件名含 `3d` 的 CSV 按 **3D 航线**编码：每航点 `geo_num3d(lat, lng, alt, level)` 生成 96 位 3D 码（经/纬/高交织），`binary128`/`bytes16_hex` 按 dim=3 输出；
- 每条记录附加 128 位二进制（`binary128`）与 16 字节大端 hex（`bytes16_hex`）及维度标记 `dim`（2/3）。

### 6.3 输出产物（out/）

| 文件 | 格式 | 说明 |
|------|------|------|
| `codes.json` | JSON | 全部 1983 条编码（1973 条 2D + 10 条 3D），含 source/type/code/code_level/dim/binary128/bytes16_hex/props |
| `codes_128.bin` | 二进制 | 每条编码 16 字节（128 位）**自描述格式**，含 geo_num + level + dim，共 16×1983 = 31728 字节 |
| `codes_16bytes.csv` | CSV | **仅一列 bytes16_hex**（每行 32 个 hex 字符），与 bin 逐条对应 |
| `http_like_response.json` | JSON | `tests/coords_to_json.py` 产物: 坐标 -> HTTP 格式 JSON 响应（19 接口, 全部 status:200） |

#### 16 字节自描述格式（v2）

每条编码占用 16 字节（128 位），字节布局如下：

```
┌─────────────────────────────────────────────┐
│ Byte 0-7:   geo_num 低 64 位 (8 bytes)      │
├─────────────────────────────────────────────┤
│ Byte 8-11:  geo_num 高 32 位 (4 bytes, 3D用)│
├─────────────────────────────────────────────┤
│ Byte 12:    level (1 byte, 0-32)            │
├─────────────────────────────────────────────┤
│ Byte 13:    dim (1 byte, 2 或 3)            │
├─────────────────────────────────────────────┤
│ Byte 14-15: reserved (2 bytes, 零填充)      │
└─────────────────────────────────────────────┘
```

**优势**：
- **自描述**：从二进制文件可完整恢复 geo_num、level、dim 所有信息
- **无需额外元数据**：层级信息内置于 16 字节中
- **向后兼容**：提供 `from_bytes16_legacy()` 函数仅返回 code

**使用示例**：

```python
import geosot_core as gc

# 编码（保存时）
code, r, c = gc.geo_num_routeB(30.55, 120.05, level=19)
buf = gc.to_bytes16(code, dim=2, level=19)  # 16 字节

# 解码（读取时，完整信息）
restored_code, level, dim = gc.from_bytes16(buf)
print(f"code={restored_code}, level={level}, dim={dim}")

# 解码（仅 code，向后兼容）
code_only = gc.from_bytes16_legacy(buf)
```

`http_like_response.json` 概览:
```json
{"request": {"lat": 39.9102778, "lng": 116.3152778, "height": 500.0, "geo_level": 21},
 "count": 19,
 "results": [{"path": "/geosot/point", "method": "POST", "status": 200,
              "body": {"server_status": 200, "geo_num": "506516229524029440-21"}}, ...]}
```
接口覆盖: point / center_point / location_point / center_point2 / lng_lat2row_col /
geo_num2row_col / row_col2geo_num / row_col2lng_lat / child_geo_num / parent_geo_num /
adjoin4_geo_num / adjoin8_geo_num / geo_num2beidou_grid_code / beidou_grid_code2geo_num /
point3d / center_point3d / extract_geo_num_2d / adjoin6_geo_num / adjoin26_geo_num。

bin/csv 顺序一致，任一条可从 16 字节自描述格式完整恢复：
```python
code, level, dim = gc.from_bytes16(buf)  # 返回 (geo_num, level, dim)
```
或按 `codes.json` 中的 `dim` 用 `from_binary128(s, dim)` 无损还原。

#### 产物实例（真实输出摘录）

`codes.json` 前 3 条（Polygon 覆盖网格，21 级）:
```json
{"source": "closed_area.geojson", "type": "Polygon", "code": "506519275675058176-21", "code_level": 21, "dim": 2, "bytes16_hex": "000000000000000007078498fa800000"}
{"source": "closed_area.geojson", "type": "Polygon", "code": "506519281408671744-21", "code_level": 21, "dim": 2, "bytes16_hex": "00000000000000000707849a50400000"}
{"source": "closed_area.geojson", "type": "Polygon", "code": "506519281421254656-21", "code_level": 21, "dim": 2, "bytes16_hex": "00000000000000000707849a51000000"}
```

`codes_16bytes.csv` 前 4 行（仅一列 bytes16_hex）:
```
bytes16_hex
000000000000000007078498fa800000
00000000000000000707849a50400000
00000000000000000707849a51000000
```

`codes_128.bin` 前 32 字节（16 字节 × 2 条, 大端连续写入）:
```
000000000000000007078498fa80000000000000000000000707849a50400000
```
（`codes_128.bin` 共 31728 字节 = 16 × 1983；2D 码占低 8 字节、3D 码占低 12 字节。）

### 6.4 验证

`tests/test_data_encode.py`（16 个用例，随套件共 103 个全部通过）断言:
- data/ 四文件解析数量与类型符合预期（2 条轨迹 / 10 航点 / 10 个 3D 航点 / 2 个封闭区，多边形闭合）;
- 提取编码结构完整（`-21` 层级、128 位串、16 字节 hex、dim∈{2,3}）;
- 3D 记录 10 条、96 位码、`binary128` 前 32 位为 0（右对齐）;
- `codes_128.bin` 大小 = 16×N、`codes_16bytes.csv` 仅一列且行数 = N+1;
- bin / csv / json 三产物互相一致，且从 bin 与 csv 还原的码与原码相等（含 3D dim=3 还原）。

## 七、坐标 -> HTTP 格式 JSON（非单元测试）

`tests/coords_to_json.py` 是独立于 unittest 的集成测试: 输入坐标（经纬度 + 高度 + 层级），
**直接调用 `app.py` 的 FastAPI handler**（绕过 HTTP 传输层），得到与 HTTP 接口返回
完全一致的响应体（`server_status:200` + 各接口字段），组装为
`[{"path","method","status","body"}, ...]` 保存到 `out/http_like_response.json`。

```
python tests\coords_to_json.py --lat 39.9102778 --lng 116.3152778 --height 500 --level 21
```

覆盖 19 个坐标相关接口并按依赖链校验（全部 PASS）:
- **routeB 码**: `/geosot/point`（坐标→码）→ `child`（4^(Δlevel) 个子格）、`parent`（还原父码）、
  `adjoin4/8`（4/8 邻域）、`row_col2geo_num`（行列→码往返）
- **routeA 码**: `center_point`/`center_point2`（中心点距输入 < 1 格）、`location_point`、
  `geo_num2row_col`（与经纬度行列一致）、`geo_num2beidou`/`beidou2geo_num`（北斗码互转）
- **3D**: `point3d`（24 位 hex 码）→ `center_point3d`（高度还原）、`extract_geo_num_2d`、
  `adjoin6/26`（6/26 邻域）

输出示例（与 HTTP 返回格式一致）:
```json
{"path": "/geosot/point", "method": "POST", "status": 200,
 "body": {"server_status": 200, "geo_num": "506516229524029440-21"}}
```

## 八、与 GB/T 40087 的一致性说明

1. **网格规格**: 度级 2^(9−L)°、分级 2^(15−L)′、秒级 2^(21−L)″、秒下级
   2^(32−L)/2048″ 的连续剖分与表 A.1 一致（15 级 1′、21 级 1″、32 级 1/2048″）。
2. **编码分段**: 路线 A 的度/分/秒/亚秒位域与附录 D 表 D.1 的分段二进制
   一一对应；附录 D 辅助函数 `gb_dms_binary`/`gb_deg_grid_morton`/`gb_quaternary`
   直接输出标准示例的二进制与四进制形式。
3. **高度域**: 采用附录 B 的等比剖分公式（B.3)–(B.7)），特征值与标准
   附录 B.1 表逐项吻合（差值 < 0.01 m）。
4. **已知差异（诚实声明）**:
   - `aggregation_geo_num`: 黄金为 routeA 跨层父码口径，本地按 routeB 目标层
     聚合，输出 4 项中的第 4 项来源未解（已按用户要求遗留）。
   - `line_buffer`: YAML 未提供 lats/lngs 示例，无黄金可比（INFO）。
   - 4 个 multi_* / geojson 接口因 YAML 无示例跳过精确比对。

## 九、复现说明

- 黄金比对逻辑: 对每个路径构造 YAML schema example 请求，将响应与
  `geosot_examples.json` 中该路径的 `example` 逐字段比对；
  数值容差 `max(1e-6, 1e-5*|黄金|)`。
- 服务重启闭环: `restart_and_test.py`（查进程 → 启动 → 轮询 → 全量回归）。
- 文件映射 `geofile.py` 为纯标准库实现（GeoJSON/SHP/CSV/WKT/KML/GPX），
  可直接作为非 HTTP 编码入口，也可经 CLI 批量处理。

## 十、无人机轨迹冲突检测与 PSI 计算

### 10.1 轨迹数据

`data/` 目录包含两份大规模无人机轨迹文件，用于演示航线冲突检测：

| 文件 | 航点数 | 覆盖区域 |
|------|--------|----------|
| `uav_conflict_1.csv` | 10000 | 中心 (116.300, 39.910)，约 3.4km × 3km |
| `uav_conflict_2.csv` | 10000 | 中心 (116.303, 39.910)，约 3.4km × 3km |

两条轨迹覆盖区域重叠约 95%，产生 **5100 个航线冲突点**（在同一 21 级网格内）。

使用 `tests/gen_large_trajectories.py` 可重新生成轨迹数据：

```powershell
python tests/gen_large_trajectories.py
```

### 10.2 轨迹冲突检测

`tests/test_trajectory_conflict.py` 实现轨迹冲突检测：

1. 读取两份轨迹 CSV 文件
2. 为每个航点生成 21 级网格编码（路线 B）
3. 计算两个编码集合的交集（冲突点）
4. 将交集编码以 128 位二进制保存到 `out/conflict_codes_128.bin`

```powershell
# 独立运行（显示各阶段耗时）
python tests/test_trajectory_conflict.py

# 运行 unittest
python -m unittest tests.test_trajectory_conflict -v
```

输出示例：

```
[1] 读取轨迹文件耗时: 0.0268 秒
[2] 轨迹编码耗时: 0.0621 秒
[3] 计算交集耗时: 0.0020 秒
[4] 保存二进制文件耗时: 0.0014 秒
交集大小: 5100 个编码
总耗时: 0.0923 秒
```

### 10.3 PSI（隐私集合交集）计算

`tests/test_psi_trajectory.py` 调用 `psi/frontend.exe` 进行 PSI 计算：

1. 读取两份轨迹文件，编码后分别保存为 `out/trajectory_party1.bin` 和 `out/trajectory_party2.bin`
2. 启动两方 PSI 协议（Receiver/Sender）进行隐私集合交集计算
3. 交集结果保存到 `out/psi_result_party1.bin`

```powershell
python tests/test_psi_trajectory.py
```

输出文件：

| 文件 | 大小 | 说明 |
|------|------|------|
| `trajectory_party1.bin` | 160000 字节 | 轨迹1编码 (10000 × 16) |
| `trajectory_party2.bin` | 160000 字节 | 轨迹2编码 (10000 × 16) |
| `psi_result_party1.bin` | 81600 字节 | PSI 交集结果 (5100 × 16) |

单独执行 PSI 的两方命令：

```powershell
# Receiver (Server) - 获得交集结果
./psi/frontend.exe -in ./out/trajectory_party1.bin -r 1 -server 1 -out ./out/psi_out.bin -noSort -receiverSize 10000 -senderSize 10000 -nt 8

# Sender (Client) - 不获得结果（PSI 协议设计）
./psi/frontend.exe -in ./out/trajectory_party2.bin -r 0 -server 0 -noSort -receiverSize 10000 -senderSize 10000 -nt 8
```

PSI 执行详情：

```
[Client/Sender]
  - reading set: 18ms
  - connecting: 0ms
  - running PSI: 28ms

[Server/Receiver]
  - reading set: 8ms
  - connecting: 514ms (等待客户端)
  - running PSI: 28ms
  - Writing output: 0ms

结果: 5100 个交集元素
```

性能数据：

| 阶段 | 耗时 |
|------|------|
| 轨迹1编码 | ~0.04 秒 |
| 轨迹2编码 | ~0.03 秒 |
| PSI 计算 | ~0.56 秒 |
| **总耗时** | **~0.63 秒** |

> **注意**: PSI 协议中只有 Receiver 会获得交集结果，Sender 不会得到输出，这是隐私集合交集协议的正常设计。

## 十一、空域网格计算（无人机低空导航）

### 11.1 功能概述

`src/geosot_core.py` 中的 `airspace_grids` 函数用于计算指定空域包含的 3D 网格编码。
该功能适用于无人机低空导航场景，给定空域的上下边界多边形和高度范围，计算空域内
包含的所有网格，并将网格编码保存为 128 位二进制文件。

**核心函数：**

```python
def airspace_grids(lower_polygon, upper_polygon, h_min, h_max, level):
    """计算空域包含的 3D 网格编码。

    参数:
        lower_polygon: 下边界 [(lng, lat), ...]
        upper_polygon: 上边界 [(lng, lat), ...]
        h_min, h_max: 高度范围 (米)
        level: 网格层级
    返回: list of 3D grid codes
    """
```

**实现原理：**

1. 使用 DDA 算法（数字微分分析）计算多边形边界经过的 2D 网格
2. 对多边形内部进行行填充，得到完整的 2D 网格覆盖集合
3. 计算上下边界的交集（共同覆盖的 2D 区域）
4. 根据高度范围和层级计算高度层索引
5. 对每个 (行, 列, 高度层) 组合生成 3D 网格编码（`interleave3` 交织）

### 11.2 德清县空域示例

以浙江省湖州市德清县（面积约 936 平方公里）为下边界，演示空域网格计算：

**空域参数：**

| 参数 | 值 |
|------|-----|
| 下边界 | 东经 119.75°~120.35°，北纬 30.433°~30.700° |
| 上边界 | 内缩后的矩形区域（119.76°~120.34°，30.443°~30.690°） |
| 高度范围 | 0m ~ 1000m（低空导航典型高度） |
| 网格层级 | Level 19（约 11m × 11m 分辨率） |

**运行测试：**

```powershell
# 独立运行（带详细输出）
python tests/test_airspace_grids.py

# 运行 unittest
python -m unittest tests.test_airspace_grids -v
```

**计算结果：**

```
空域参数:
  下边界: [(119.75, 30.433), (120.35, 30.433), (120.35, 30.7), (119.75, 30.7)]
  上边界: [(119.76, 30.443), (120.34, 30.443), (120.34, 30.69), (119.76, 30.69)]
  高度范围: 0m - 1000m
  网格层级: 19

计算结果:
  空域包含网格数: 1,054,368
  计算耗时: 4.8 秒

已保存到: out/airspace_grids.bin
  文件大小: 16869888 字节 (1054368 × 16)
```

### 11.3 输出产物

| 文件 | 大小 | 说明 |
|------|------|------|
| `airspace_grids.bin` | 17 MB | 3D 网格编码（1054368 × 16 字节） |

二进制文件格式：每条编码 16 字节（128 位），大端序存储，3D 码占低 12 字节（96 位）。

### 11.4 测试套件

`tests/test_airspace_grids.py` 包含 12 个测试用例，分 4 个测试类：

| 测试类 | 用例数 | 测试内容 |
|--------|--------|----------|
| `TestPointInPolygon` | 4 | 点在多边形内/外判断（射线法） |
| `TestPolygonCells2D` | 2 | 多边形 2D 网格覆盖计算 |
| `TestAirspaceGrids` | 5 | 基本空域、无重叠、高度范围、层级影响、二进制保存/读回 |
| `TestAirspaceGridsPerformance` | 1 | 性能测试（德清县区域，约 100 万网格） |

全部测试通过，计算性能约 5 秒（100 万网格）。

### 11.5 应用场景

该功能适用于以下无人机低空导航场景：

- **空域容量评估**：计算指定空域可容纳的网格数量
- **航线规划**：获取空域内的可用网格集合，用于航线搜索
- **冲突检测**：多架无人机共享空域时，基于网格进行冲突预判
- **空域管理**：为低空空域管理系统提供网格化的空间索引

> **提示**：可通过调整 `level` 参数控制网格分辨率。Level 19 约 11m 精度，
> Level 20 约 5.5m 精度，Level 21 约 2.7m 精度。层级越高，网格数量越多，
> 计算时间越长。

## 十二、空域可用性计算（城市低空监管）

### 12.1 功能概述

`tests/test_airspace_availability.py` 实现城市低空空域可用性计算，演示完整的空域查询流程：

1. **城市网格化**：将城市区域划分为高精度 3D 网格（Level 21, ~31m × 27m × 31m）
2. **占用标记**：标记建筑物、禁飞区、通信塔等占用的网格
3. **可用网格集合 Y**：从全部网格中排除占用网格，得到可用网格
4. **查询空域 X**：定义一个查询空域，计算其包含的网格
5. **交集计算**：
   - 明文计算 X ∩ Y（空域内可用网格）
   - PSI 计算 X ∩ Y（隐私集合交集）
6. **结果对比**：验证 PSI 结果与明文结果一致

**核心思路**：使用**集合差运算**标记占用 —— 可用网格 = 全部网格 - 占用网格。
查询空域与可用网格取交集，即为空域内的可用网格。

### 12.2 场景参数

**网格参数**：

| 参数 | 值 |
|------|-----|
| 网格层级 | Level 21（1″ 网格） |
| 网格尺寸 | ~31m (N-S) × 27m (E-W) × 31m (高度) |
| 编码维度 | 3D（经纬度 + 高度） |

**区域定义**（德清县附近）：

| 区域 | 经度范围 | 纬度范围 | 高度范围 | 网格数 |
|------|----------|----------|----------|--------|
| 城市总区域 | 120.000°~120.028° | 30.540°~30.567° | 0~500m | 158,368 |
| 占用区1（建筑群） | 120.020°~120.025° | 30.558°~30.562° | 0~100m | 810 |
| 占用区2（禁飞区） | 120.008°~120.014° | 30.545°~30.550° | 0~500m | 6,336 |
| 占用区3（通信塔） | 120.003°~120.005° | 30.560°~30.562° | 0~300m | 576 |
| 查询空域 | 120.006°~120.018° | 30.544°~30.554° | 50~200m | 7,920 |

### 12.3 运行方式

```powershell
# 独立运行（完整流程演示）
python tests/test_airspace_availability.py

# 运行 unittest
python tests/test_airspace_availability.py --test
# 或
python -m unittest tests.test_airspace_availability -v
```

### 12.4 计算结果

```
======================================================================
城市低空空域可用性计算演示
======================================================================

网格层级: Level 21 (1" 网格, ~31m × 27m × 31m)
城市区域: (120.0, 30.54) - (120.028, 30.567)
高度范围: 0m - 500m

[1] 生成城市全部网格...
    城市总网格: 158,368 (耗时 0.91s)

[2] 标记占用区域...
    建筑群:   810 个网格 (100m 以下)
    禁飞区:   6,336 个网格 (全高度)
    通信塔:   576 个网格 (300m 以下)
    占用合计: 7,722 个网格

[3] 可用网格集合 Y: 150,646

[4] 查询空域 (120.006-120.018, 30.544-30.554, 50-200m)...
    查询空域网格 X: 7,920

[5] 明文交集计算 (X ∩ Y)...
    |X| = 7,920
    |Y| = 150,646
    |X ∩ Y| = 5,940 (可用网格)
    X 中被占用: 1,980 (25.0%)
    耗时: 0.001300s

[6] PSI 隐私集合交集...
    PSI 交集大小: 5,940
    PSI 耗时: 0.572s

======================================================================
结果对比:
  明文交集: 5,940 个可用网格
  PSI 交集: 5,940 个可用网格
  一致性:   PASS [OK]
======================================================================
```

### 12.5 输出产物

所有输出文件保存在 `out/airspace_availability/` 目录：

| 文件 | 大小 | 说明 |
|------|------|------|
| `available_grids_Y.bin` | 2,410,336 字节 | 可用网格集合 Y（150,646 × 16） |
| `query_airspace_X.bin` | 126,720 字节 | 查询空域网格 X（7,920 × 16） |
| `plaintext_intersection.bin` | 95,040 字节 | 明文交集结果（5,940 × 16） |
| `psi_intersection.bin` | 95,040 字节 | PSI 交集结果（5,940 × 16） |

二进制文件格式：每条编码 16 字节（128 位）自描述格式，包含 geo_num + level + dim。

### 12.6 测试套件

`tests/test_airspace_availability.py` 包含 4 个测试用例：

| 测试用例 | 测试内容 |
|----------|----------|
| `test_data_generation` | 数据生成正确性：城市网格 > 1万，占用网格 > 100，可用 + 占用 = 全部 |
| `test_query_airspace` | 查询空域包含占用网格和可用网格 |
| `test_plaintext_intersection` | 明文交集计算正确，文件往返验证一致 |
| `test_psi_intersection` | PSI 交集结果与明文结果完全一致 |

### 12.7 核心代码

**生成矩形区域 3D 网格**：

```python
def generate_rect_grids(lng_min, lat_min, lng_max, lat_max, h_min, h_max, level):
    """生成矩形区域内的所有 3D 网格编码。"""
    cd = gc.cell_deg(level)      # 网格经纬度跨度
    hc = gc.height_cell(level)   # 高度单元格大小

    codes = set()
    lat = lat_min
    while lat < lat_max:
        lng = lng_min
        while lng < lng_max:
            h = h_min
            while h < h_max:
                code = gc.geo_num3d(lat, lng, h, level)
                codes.add(code)
                h += hc
            lng += cd
        lat += cd
    return codes
```

**占用标记与可用网格计算**：

```python
# 生成城市全部网格
all_grids = generate_rect_grids(CITY_LNG_MIN, CITY_LAT_MIN, ...)

# 生成占用区域网格（建筑群 + 禁飞区 + 通信塔）
occ1 = generate_rect_grids(OCC1_LNG_MIN, OCC1_LAT_MIN, ...)
occ2 = generate_rect_grids(OCC2_LNG_MIN, OCC2_LAT_MIN, ...)
occ3 = generate_rect_grids(OCC3_LNG_MIN, OCC3_LAT_MIN, ...)
occupied = (occ1 | occ2 | occ3) & all_grids  # 合并占用，限制在城市范围内

# 可用网格 = 全部 - 占用
available = all_grids - occupied  # 集合 Y

# 查询空域
query = generate_rect_grids(QUERY_LNG_MIN, QUERY_LAT_MIN, ...)  # 集合 X

# 明文交集
plaintext = query & available  # X ∩ Y
```

**PSI 计算**：

```python
# Receiver (X 方) - 获得交集结果
cmd_receiver = [PSI_EXE, '-in', x_path, '-r', '1', '-server', '1',
                '-out', psi_out, '-noSort',
                '-receiverSize', str(x_size), '-senderSize', str(y_size), '-nt', '8']

# Sender (Y 方) - 不获得结果
cmd_sender = [PSI_EXE, '-in', y_path, '-r', '0', '-server', '0',
              '-noSort', '-receiverSize', str(x_size), '-senderSize', str(y_size), '-nt', '8']
```

### 12.8 应用场景

该功能适用于以下城市低空监管场景：

- **无人机航线规划**：查询空域内可用网格，避开建筑物和禁飞区
- **实时空域查询**：快速判断指定区域是否可供无人机飞行
- **隐私保护查询**：使用 PSI 协议，查询方无需暴露完整可用网格数据
- **动态空域管理**：实时更新占用网格（新增建筑物、临时禁飞区），动态计算可用空域
- **多运营商协调**：不同运营商持有各自的占用数据，通过 PSI 计算公共可用区域

> **提示**：查询空域覆盖了部分占用区域（禁飞区），因此交集结果中 25% 的网格被占用，
> 75% 的网格可用。实际应用中，占用比例取决于城市建筑密度和禁飞区分布。

## 十三、CPSI 交集基数计算

### 13.1 功能概述

`tests/test_cpsi_cardinality.py` 实现 CPSI (Circuit PSI) 交集基数计算。与普通 PSI 不同，
CPSI 仅返回交集的**基数**（交集大小），不返回具体的交集元素，结果直接输出在终端而不存储到文件。

**与普通 PSI 的区别：**

| 特性 | 普通 PSI | CPSI |
|------|----------|------|
| 输出内容 | 完整交集元素集合 | 仅交集基数（数量） |
| 输出方式 | 写入二进制文件 | 终端打印 |
| 隐私保护 | 强（不泄露交集大小） | 较弱（泄露交集大小） |
| 适用场景 | 需要知道具体交集元素 | 仅需知道交集规模 |

### 13.2 运行方式

```powershell
# 独立运行（完整流程演示）
python tests/test_cpsi_cardinality.py

# 运行 unittest
python -m unittest tests.test_cpsi_cardinality -v
```

### 13.3 计算结果

```
[4] CPSI 交集基数计算...
    (仅返回交集大小，不返回具体元素)
    CPSI 耗时: 2.285s

  === Receiver 输出 ===
    reading set... 3ms
    connecting as server at address localhost:1212 8ms
    Validating set sizes... 0ms
    running circuit PSI (cardinality)... 1247ms
    cardinality = 5940
    receiverSize = 7920

======================================================================
结果对比:
  明文交集基数: 5,940
  CPSI 交集基数: 5,940
  一致性: PASS [OK]
======================================================================
```

### 13.4 CPSI 命令格式

CPSI 使用 `frontend.exe` 的 `-card` 标志：

```powershell
# 终端 A (Receiver = Server)
./psi/frontend.exe -in query_airspace_X.bin -r 1 -server 1 -card -v

# 终端 B (Sender = Client)
./psi/frontend.exe -in available_grids_Y.bin -r 0 -server 0 -card
```

**关键参数：**
- `-card`: 启用 Circuit PSI cardinality 模式，仅返回交集基数
- `-v`: verbose 输出，显示详细计算过程
- `-r 1`: 此方为 Receiver（获得结果）
- `-server 1`: 此方作为 IP 服务器（监听连接）

**输出格式：**
```
cardinality = 5940
receiverSize = 7920
```

### 13.5 应用场景

CPSI 适用于以下场景：

- **空域容量评估**：仅需知道查询空域内有多少可用网格，无需知道具体位置
- **隐私保护统计**：统计双方数据的重叠规模，不暴露具体重叠元素
- **资源预分配**：根据交集规模预估所需资源，无需详细交集信息
- **快速筛选**：先通过 CPSI 评估交集规模，再决定是否执行完整 PSI

> **注意**：CPSI 会泄露交集的基数信息，在隐私要求极高的场景中应谨慎使用。
> 如需完整隐私保护（不泄露交集大小），请使用普通 PSI 协议。
