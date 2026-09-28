# Cell v2 离线契约原型

`cell_contract.py` 是方案1的项目扩展，使用 Python 标准库。它不修改原生 iWhere
HTTP 路径，不提供数据库、认证授权、图推理引擎或密码执行器，也不证明具体编码
符合某一标准。业务部署仍需数据库事务、版本快照、权限控制和已验证密码引擎。

已实现：

- 明确编码命名空间、版本、二维或三维、层级、CRS及高度profile的空间身份校验；兼容本仓库
  `code="十进制码-level"` 和文档 `grid.geo_num/grid.geo_level`。
- 文档 v1 `attributes/states` 数组转换；仓库 `props` 每个字段必须提供属性类型/单位映射，
  未映射字段明确报 `PROPERTY_MAPPING_REQUIRED`，不静默丢弃。
- 项目RFC3339格式时间转换为UTC，严格 `[valid_from,valid_to)`，拒绝凭一个timestamp猜有效期。
  必须包含大写T、秒、大写Z或带冒号的时区偏移；小数秒最多6位。原型不支持闰秒或
  表示未知偏移的 `-00:00`，明确拒绝，不能把其当作UTC或静默截断精度。
- 按数据集、提供方、源记录、属性实例和修订版保留多源观测；相同修订重试幂等，
  同修订不同数据报冲突。此纯函数不是持久数据库的并发事务或全局幂等实现。
- 本地条件 TRUE/FALSE/UNKNOWN/CONFLICT 分类。未知、过期、多源矛盾不自动放行。
- CellKey 规范JSON字节，含公共匹配域、编码profile和时间桶profile。不同
  dataset/provider/source-record 不进入公共空间匹配键。返回字节**未加密**，
  不能当作隐私令牌公开；后续须交给真实PSI/MPC适配器。
- 安全算子仅生成输入句柄描述；已知但未接引擎返回 `NOT_IMPLEMENTED`，
  未登记算子返回 `UNSUPPORTED`，不产生假密码结果。

## 运行示例

在复现目录运行以下Python代码；示例原码仅为结构示例，模块不验证其空间语义。

```python
import json
from pathlib import Path
from cell_contract import v1_to_v2, canonical_cell_key
from cell_contract import evaluate_local_condition, describe_secure_operator

example = json.loads(Path("cell_contract_examples.json").read_text(encoding="utf-8"))
cell = v1_to_v2(example["v1_cell"], **example["ingestion_context"], **example["profile"])
print(json.dumps(cell, ensure_ascii=False, indent=2))
print(evaluate_local_condition(cell["observations"], **example["local_condition"]))
key = canonical_cell_key(cell["grid"], **example["matching_context"])
print(key.decode("utf-8"))  # 仅在此公开测试数据上演示，生产环境禁止日志输出秘密键
print(describe_secure_operator(**example["secure_operator_description"]))
```

预期：风速大于8的本地条件为FALSE；安全比较算子描述返回NOT_IMPLEMENTED。
条件FALSE本身不是航路允许结论，完整任务仍需组合全部适用约束和完整性状态。

```powershell
python -m unittest discover -s tests -p test_cell_contract.py -v
```

## 明确边界和后续接入

1. 混合来源的Cell容器先按实际提供方拆分，再分别传入可信接入上下文。不能用
   任意客户端source声明取代身份认证。本地字典中的source_id不会自动执行认证。
2. 本原型规范值但不做单位换算。上游必须按属性字典统一单位，条件threshold与
   观测使用同一单位；不同来源的融合必须由独立、版本化融合策略执行。
3. 嵌套`properties.meteorological`先由数据源专用映射器转换，不静默猜嵌套语义。
   缺少原始geo_num的`G18_T...`别名不能作为唯一空间键自动恢复。
4. `append_observations`处理源观测身份；跨格网分布的场值必须给不同观测实例ID，
   或使用数据库中的独立对象—格网绑定表，不能复用同一ID覆盖不同格网的值。
5. canonical_cell_key只表达同层同桶相等。跨层包含、时间区间相交、轨迹分段和
   覆盖完整性需要额外安全对齐/算子；普通PSI不会自动解决。
6. grid的命名空间和profile由双方预先约定。工程码与标准码不能只改namespace
   就视为转换成功，必须执行已核验的编码转换，并登记实现/映射版本。
   `normalize_grid` 对 `数字-level` 剥离后缀只适用于本项目既有v1导出的语法，
   不是任意外部编码体系的通用解析规则。调用方须在原始数据层完整保留原码及来源，
   规范化结果不能覆盖原始码；其他来源应先通过专用适配器确认语法再调用。
7. input_handles和output_policy_id只是描述。本模块不校验句柄存在、使用权限、
   密钥域兼容或策略授权；真正执行前必须由后端完成这些检查。

拟定项目API可以包括 `/v2/datasets/{id}/ingest-jobs`、
`/v2/datasets/{id}/cells:query`、`/v2/knowledge/context:query` 和
`/v2/secure/jobs`；这些未在本原型注册为HTTP路由，也不是iWhere原生API。
