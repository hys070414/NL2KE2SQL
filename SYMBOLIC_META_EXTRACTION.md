# 符号化元信息提取 - 代码与测试结果整理

## 📁 目录结构

```
symbolic_meta_extraction/
├── README.md                          # 本文档
├── core/                              # 核心代码
│   ├── symbolic_meta_extractor.py     # 符号化元信息提取器（完整版）
│   ├── symbolic_meta_extraction.py    # 简化版提取器
│   └── symbolic_ke2sql.py             # KE转SQL模块
├── test/                              # 测试代码
│   ├── test_ke2sql_with_symbolic.py  # 主测试脚本（NL2KE2SQL完整流程）
│   ├── test_symbolic_meta.py          # 元信息提取测试
│   └── demo_symbolic_extraction.py    # 提取器演示
├── data/                              # 数据
│   ├── super_ontology.json             # 本体定义（199个数据库概念）
│   └── spider/                        # Spider数据集
├── results/                           # 测试结果
│   ├── experiment_results_full.png     # 实验结果柱状图
│   └── test_summary.txt               # 测试摘要
└── docs/                              # 文档
    └── SYMBOLIC_NL2KE_GUIDE.md        # 符号化NL2KE指南
```

---

## 📊 测试结果摘要

### 完整测试结果（278个样本，139个数据库）

| 指标 | Baseline | +Symbolic | 提升 |
|------|----------|-----------|------|
| **准确率** | 39.9% (111/278) | **50.7%** (141/278) | **+27.0%** |
| 符号化提取时间 | - | **0.19ms** | 几乎零成本 |
| LLM KE生成时间 | 27.16s | 27.16s | - |
| LLM SQL生成时间 | 10.05s | 10.05s | - |

### 结果分布
- 两者都正确: 99
- 仅Baseline正确: 12
- 仅Symbolic正确: **42** ← 符号化元信息帮助解决的问题
- 两者都错误: 125

---

## 🔧 核心代码说明

### 1. symbolic_meta_extractor.py

纯符号化元信息提取器，基于规则无需LLM参与。

**提取的元信息类型：**
- `KeyValues`: 问题中的具体值（数字、字符串、年份等）
- `CalcMode`: 计算模式（none, age_at_release, ratio_comparison等）
- `Aggregation`: 聚合函数（count, sum, avg, min, max）
- `SubqueryTable`: 涉及的数据库表
- `OutputColumns`: 输出列
- `OrderBy`: 排序方向（asc/desc）
- `Limit`: 限制数量

**关键规则示例：**

```python
# CalcMode识别
CALCMODE_PATTERNS = {
    "age_at_release": [r"\bage.*at.*release\b", r"\b发布.*年龄\b"],
    "ratio_comparison": [r"\btimes\b", r"\brate\b", r"\b倍\b"],
    "years_since_event": [r"\byears.*since\b", r"\b多少.*年.*前\b"]
}

# KeyValues提取
keyvalues = []
quoted = re.findall(r'"([^"]+)"', question)  # 引号内容
years = re.findall(r'\b(19\d{2}|20\d{2})\b', question)  # 年份
nums = re.findall(r'\b(\d+(?:\.\d+)?)\b', question)  # 数字
```

### 2. test_ke2sql_with_symbolic.py

NL2KE2SQL完整测试脚本，对比Baseline和+Symbolic的效果。

**测试流程：**
```
问题 + 本体 → [Baseline: 无元信息 | +Symbolic: 有符号化元信息]
           ↓
        LLM生成KE
           ↓
        LLM实现KE2SQL
           ↓
      执行SQL比对结果
```

**使用方式：**
```bash
# 设置API Key
export DASHSCOPE_API_KEY="your-api-key"

# 运行测试
python test_ke2sql_with_symbolic.py
```

---

## 📈 实验结果可视化

![实验结果](results/experiment_results_full.png)

**图表说明：**
- 左图：SQL生成准确率对比（39.9% → 50.7%）
- 右图：结果分类统计
  - 绿色：两者都正确 (99)
  - 蓝色：仅Baseline正确 (12)
  - 橙色：仅Symbolic正确 (42) ← 关键提升
  - 红色：两者都错误 (125)

---

## 🎯 关键发现

1. **符号化元信息显著提升准确率**
   - 准确率从 39.9% 提升到 50.7%，相对提升 **+27.0%**

2. **零成本提取**
   - 符号化元信息提取仅需 **0.19ms**，相比LLM的37秒总时间几乎为零

3. **42个问题因符号化元信息而正确**
   - 这些问题在Baseline下失败，但添加符号化元信息后成功

4. **仍然存在的挑战**
   - 125个问题两者都失败，主要涉及复杂的多表JOIN和嵌套查询

---

## 📋 数据集覆盖

| 数据集 | 数据库数 | 与本体交集 |
|--------|----------|-----------|
| Spider | 140 | 139 |
| BIRD | 11 | 1 (formula_1) |
| 本体 | 199 | - |

---

## 🔗 相关文档

- `SYMBOLIC_NL2KE_GUIDE.md` - 符号化NL2KE详细指南
- `META_INFO_DEFINITION.md` - 元信息定义说明
- `super_ontology.json` - 本体定义文件

---

## 📝 引用

如果您使用此代码，请引用：
```
NL2KE2SQL Symbolic Metadata Extraction
https://github.com/your-repo/symbolic-nl2ke
```
