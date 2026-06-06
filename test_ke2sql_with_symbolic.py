#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
符号化元信息提取在NL2KE2SQL上的效果测试

测试流程：
1. Baseline: 问题 + 本体 → LLM生成KE → LLM实现KE2SQL → SQL结果
2. +Symbolic: 问题 + 本体 + 符号化元信息 → LLM生成KE → LLM实现KE2SQL → SQL结果

比较：SQL执行结果与Ground Truth的匹配程度
"""

import json
import time
import re
import sqlite3
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)

# ==================== 配置 ====================
TEST_DATA_PATH = Path("spider/spider_data/train_spider.json")
DB_PATH = Path("spider/spider_data/database")
ONTOLOGY_PATH = Path("super_ontology.json")

# ==================== 符号化元信息提取器 ====================
@dataclass
class SymbolicMeta:
    KeyValues: List[str] = field(default_factory=list)
    CalcMode: str = "none"
    Aggregation: Optional[str] = None
    OrderBy: Optional[str] = None
    Limit: Optional[int] = None
    
    def to_text(self) -> str:
        parts = []
        if self.KeyValues:
            parts.append(f"KeyValues: {', '.join(self.KeyValues)}")
        if self.Aggregation:
            parts.append(f"Aggregation: {self.Aggregation}")
        if self.OrderBy:
            parts.append(f"OrderBy: {self.OrderBy}")
        if self.Limit:
            parts.append(f"Limit: {self.Limit}")
        if self.CalcMode != "none":
            parts.append(f"CalcMode: {self.CalcMode}")
        return "\n".join(parts) if parts else "No special metadata"


class SymbolicExtractor:
    """符号化元信息提取器"""
    
    CALCMODE_PATTERNS = {
        "age_at_release": [r"\bage.*at.*release\b", r"\bat.*time.*release\b"],
        "age_comparison": [r"\btwice.*age\b", r"\bhow old\b"],
        "ratio_comparison": [r"\b(\d+)\s*times\b", r"\brate\b", r"\bratio\b"]
    }
    
    AGGREGATION_PATTERNS = {
        "count": [r"\bhow many\b", r"\bcount\b", r"\bnumber of\b", r"\b多少\b"],
        "sum": [r"\bsum\b", r"\btotal\b"],
        "avg": [r"\baverage\b", r"\bavg\b", r"\bmean\b", r"\b平均\b"],
        "min": [r"\bminimum\b", r"\bmin\b", r"\bsmallest\b", r"\blowest\b", r"\blowest\b", r"\blowest\b"],
        "max": [r"\bmaximum\b", r"\bmax\b", r"\blargest\b", r"\bbiggest\b", r"\bhighest\b", r"\bhighest\b", r"\bmost\b"]
    }
    
    ORDERBY_DESC_PATTERNS = [r"\bhighest\b", r"\bmost\b", r"\blargest\b", r"\bbiggest\b", r"\bdescending\b"]
    ORDERBY_ASC_PATTERNS = [r"\blowest\b", r"\bleast\b", r"\bsmallest\b", r"\bminimum\b", r"\bascending\b", r"\bfirst\b"]
    
    LIMIT_PATTERNS = [r"\btop\s+(\d+)\b", r"\bfirst\s+(\d+)\b", r"\b(\d+)\s+(?:items?|results?)\b"]
    
    def extract(self, question: str) -> Tuple[SymbolicMeta, float]:
        start = time.time()
        q = question.lower()
        
        # 清理问题：排除K-12等教育级别，保留年龄范围
        q_clean = re.sub(r'[Kk]-\d+', 'K-GRADE', question).lower()
        
        # KeyValues
        kv = []
        quoted = re.findall(r'"([^"]+)"', q_clean) + re.findall(r"'([^']+)'", q_clean)
        kv.extend(quoted)
        years = re.findall(r'\b(19\d{2}|20\d{2})\b', q_clean)
        kv.extend(years)
        nums = re.findall(r'\b(\d+(?:\.\d+)?)\b', q_clean)
        for n in nums:
            if n not in kv and len(n) != 4:
                kv.append(n)
        
        # CalcMode
        calcmode = "none"
        for mode, patterns in self.CALCMODE_PATTERNS.items():
            for p in patterns:
                if re.search(p, q):
                    calcmode = mode
                    break
        
        # Aggregation
        agg = None
        for a, patterns in self.AGGREGATION_PATTERNS.items():
            for p in patterns:
                if re.search(p, q):
                    agg = a
                    break
            if agg:
                break
        
        # OrderBy
        ob = None
        for p in self.ORDERBY_DESC_PATTERNS:
            if re.search(p, q):
                ob = "DESC"
                break
        if not ob:
            for p in self.ORDERBY_ASC_PATTERNS:
                if re.search(p, q):
                    ob = "ASC"
                    break
        
        # Limit
        lim = None
        for p in self.LIMIT_PATTERNS:
            m = re.search(p, q)
            if m:
                lim = int(m.group(1))
                break
        
        return SymbolicMeta(KeyValues=kv, CalcMode=calcmode, Aggregation=agg, OrderBy=ob, Limit=lim), time.time() - start


# ==================== LLM API调用 ====================
def call_api(prompt: str, max_tokens: int = 512) -> Tuple[str, float]:
    try:
        from openai import OpenAI
        # 使用DeepSeek V4 Flash (通过DashScope)
        api_key = os.environ.get("DASHSCOPE_API_KEY", "sk-cb52e47466e54085964e8239e3588105")
        client = OpenAI(
            api_key=api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
        start = time.time()
        resp = client.chat.completions.create(
            model="deepseek-v4-flash",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=max_tokens,
            timeout=120.0
        )
        return resp.choices[0].message.content.strip(), time.time() - start
    except Exception as e:
        print(f"API错误: {e}")
        return "", 0.0


# ==================== Prompt模板 ====================

# Step 1: NL → KE
PROMPT_KE_BASELINE = """Given the database ontology and question, generate the Knowledge Equation (KE).

ONTOLOGY:
{ontology}

QUESTION: {question}

Output ONLY the KE in this format (no SQL, no explanation):
Count = COUNT(Singer);
output = {{ SingerName(s), Count | s: Singer }};
"""


PROMPT_KE_WITH_META = """Given the database ontology, question, and metadata hints, generate the Knowledge Equation (KE).

ONTOLOGY:
{ontology}

QUESTION: {question}

METADATA HINTS:
{metadata}

Output ONLY the KE in this format (no SQL, no explanation):
Count = COUNT(Singer);
output = {{ SingerName(s), Count | s: Singer, SingerSongName(s) = "Gentleman" }};
"""

# Step 2: KE → SQL
PROMPT_SQL = """You are a KE to SQL converter. Given the database schema and a KE, generate the SQL query.

SCHEMA:
{schema}

KE:
{ke}

Output SQL query only:"""


# ==================== 工具函数 ====================
def get_ontology_text(db_id: str) -> str:
    """获取指定数据库的本体信息"""
    if not ONTOLOGY_PATH.exists():
        return ""
    
    with open(ONTOLOGY_PATH, encoding="utf-8") as f:
        ontology = json.load(f)
    
    concepts = ontology.get("concepts", {})
    lines = []
    
    # 找到该数据库相关的概念
    for concept_name, concept_data in concepts.items():
        sources = concept_data.get("sources", {})
        if db_id in sources:
            source = sources[db_id]
            table = source.get("table", "")
            slots = source.get("slots", {})
            
            slot_lines = []
            for slot_name, col_name in slots.items():
                slot_lines.append(f"  {slot_name} -> {col_name}")
            
            lines.append(f"CONCEPT {concept_name} (Table: {table}):")
            lines.extend(slot_lines)
            lines.append("")
    
    return "\n".join(lines)


def get_schema(db_path: Path) -> str:
    """获取数据库schema"""
    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        lines = []
        cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
        for (tbl,) in cur.fetchall():
            lines.append(f"Table {tbl}:")
            cur.execute(f"PRAGMA table_info({tbl});")
            for col in cur.fetchall():
                lines.append(f"  - {col[1]}: {col[2]}")
        conn.close()
        return "\n".join(lines)
    except:
        return ""


def find_db(db_id: str) -> Optional[Path]:
    # Spider格式: database/{db_id}/{db_id}.sqlite
    p1 = DB_PATH / db_id / f"{db_id}.sqlite"
    if p1.exists():
        return p1
    # BIRD格式: dev_databases/{db_id}/{db_id}.sqlite
    p2 = Path(f"BIRD/dev_20240627/dev_databases/{db_id}/{db_id}.sqlite")
    if p2.exists():
        return p2
    return None


def execute_sql(db_path: Path, sql: str) -> Optional[List[Tuple]]:
    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute(sql)
        res = cur.fetchall()
        conn.close()
        return [tuple(r) for r in res]
    except:
        return None


def clean_sql(sql: str) -> str:
    sql = sql.replace("```sql", "").replace("```", "").strip()
    idx = sql.lower().find("select")
    return sql[idx:].strip() if idx >= 0 else sql.strip()


def extract_ke(ke_text: str) -> str:
    """从LLM输出中提取KE部分"""
    if not ke_text:
        return ""
    # 去掉常见的markdown代码块标记
    ke_text = ke_text.replace("```ke", "").replace("```", "").strip()
    # 如果包含"KE:"标记，只返回其后的内容
    if "KE:" in ke_text.upper():
        idx = ke_text.upper().find("KE:")
        ke_text = ke_text[idx+3:].strip()
    # 如果是多行，返回全部（去掉首尾空白）
    return ke_text.strip()


def results_match(r1, r2) -> bool:
    if not r1 or not r2:
        return False
    if len(r1) != len(r2):
        return False
    try:
        return sorted(r1) == sorted(r2)
    except:
        return False


# ==================== 测试主逻辑 ====================
def run_test(max_samples: int = 20):
    print("=" * 80)
    print("符号化元信息提取在NL2KE2SQL上的效果测试")
    print("=" * 80)
    print()
    
    # 加载数据
    with open(TEST_DATA_PATH, encoding="utf-8") as f:
        data = json.load(f)
    
    print(f"数据集大小: {len(data)}, 测试样本: {min(max_samples, len(data))}")
    print()
    
    extractor = SymbolicExtractor()
    stats = {"baseline": 0, "symbolic": 0, "both": 0, "none": 0, "skip": 0}
    meta_total_time = 0
    ke_total_time = 0
    sql_total_time = 0
    
    for i, item in enumerate(data[:max_samples], 1):
        db_id = item.get("db_id", "")
        question = item.get("question", "")
        gold_sql = item.get("query", "")  # query字段是字符串SQL
        
        if not all([db_id, question, gold_sql]):
            stats["skip"] += 1
            continue
        
        db_path = find_db(db_id)
        if not db_path:
            stats["skip"] += 1
            continue
        
        ontology = get_ontology_text(db_id)
        schema = get_schema(db_path)
        gold_res = execute_sql(db_path, gold_sql)
        
        print(f"【{i}/{max_samples}】{db_id}")
        print(f"  Q: {question[:70]}...")
        
        # ========== Baseline: 无符号化元信息 ==========
        meta_baseline = SymbolicMeta()
        meta_time_baseline = 0
        
        # Step 1: NL → KE (Baseline)
        prompt_ke_baseline = PROMPT_KE_BASELINE.format(ontology=ontology, question=question)
        ke_text_baseline, ke_time_baseline = call_api(prompt_ke_baseline, max_tokens=384)
        ke_baseline = extract_ke(ke_text_baseline)
        
        # Step 2: KE → SQL (Baseline)
        prompt_sql_baseline = PROMPT_SQL.format(schema=schema, ke=ke_baseline)
        sql_baseline_raw, sql_time_baseline = call_api(prompt_sql_baseline, max_tokens=512)
        sql_baseline = clean_sql(sql_baseline_raw)
        res_baseline = execute_sql(db_path, sql_baseline)
        match_baseline = results_match(res_baseline, gold_res)
        
        # ========== +Symbolic: 有符号化元信息 ==========
        meta_symbolic, meta_time_symbolic = extractor.extract(question)
        meta_text = meta_symbolic.to_text()
        
        # Step 1: NL → KE (+Symbolic)
        prompt_ke_symbolic = PROMPT_KE_WITH_META.format(
            ontology=ontology, 
            question=question, 
            metadata=meta_text
        )
        ke_text_symbolic, ke_time_symbolic = call_api(prompt_ke_symbolic, max_tokens=384)
        ke_symbolic = extract_ke(ke_text_symbolic)
        
        # Step 2: KE → SQL (+Symbolic)
        prompt_sql_symbolic = PROMPT_SQL.format(schema=schema, ke=ke_symbolic)
        sql_symbolic_raw, sql_time_symbolic = call_api(prompt_sql_symbolic, max_tokens=512)
        sql_symbolic = clean_sql(sql_symbolic_raw)
        res_symbolic = execute_sql(db_path, sql_symbolic)
        match_symbolic = results_match(res_symbolic, gold_res)
        
        # 统计
        meta_total_time += meta_time_symbolic
        ke_total_time += ke_time_baseline + ke_time_symbolic
        sql_total_time += sql_time_baseline + sql_time_symbolic
        
        if match_baseline:
            stats["baseline"] += 1
        if match_symbolic:
            stats["symbolic"] += 1
        if match_baseline and match_symbolic:
            stats["both"] += 1
        if not match_baseline and not match_symbolic:
            stats["none"] += 1
        
        print(f"  Baseline: {'OK' if match_baseline else 'FAIL'} ({ke_time_baseline:.1f}s + {sql_time_baseline:.1f}s)")
        print(f"  +Symbolic: {'OK' if match_symbolic else 'FAIL'} ({meta_time_symbolic*1000:.1f}ms + {ke_time_symbolic:.1f}s + {sql_time_symbolic:.1f}s)")
        print(f"  Meta: {meta_text[:50]}...")
        print()
    
    # 总结
    total = max_samples - stats["skip"]
    print("=" * 80)
    print("测试结果总结")
    print("=" * 80)
    print(f"有效样本: {total}, 跳过: {stats['skip']}")
    print()
    print(f"Baseline准确率: {stats['baseline']}/{total} ({stats['baseline']/total*100:.1f}%)")
    print(f"+Symbolic准确率: {stats['symbolic']}/{total} ({stats['symbolic']/total*100:.1f}%)")
    print(f"两者都正确: {stats['both']}, 两者都错误: {stats['none']}")
    print()
    print(f"符号化元信息提取平均时间: {meta_total_time/total*1000:.2f}ms")
    print(f"LLM KE生成平均时间: {ke_total_time/total:.2f}s")
    print(f"LLM SQL生成平均时间: {sql_total_time/total:.2f}s")
    
    improvement = (stats["symbolic"] - stats["baseline"]) / max(1, stats["baseline"]) * 100
    print(f"\n准确率变化: {'+' if improvement >= 0 else ''}{improvement:.1f}%")


if __name__ == "__main__":
    import sys
    # 设置qwen API密钥
    if not os.environ.get("DASHSCOPE_API_KEY"):
        os.environ["DASHSCOPE_API_KEY"] = "sk-cb52e47466e54085964e8239e3588105"
    # 使用dev.json测试（20个数据库）
    run_test(max_samples=20)
