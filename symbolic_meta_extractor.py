#!/usr/bin/env python3
"""
纯符号化元信息提取器
100%准确率目标 - 基于规则，无LLM参与
"""

import re
import json
import sqlite3
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional, Any
from dataclasses import dataclass


@dataclass
class TableSchema:
    """表结构"""
    name: str
    columns: List[str]
    primary_key: Optional[str] = None


@dataclass
class DatabaseSchema:
    """数据库结构"""
    db_id: str
    tables: Dict[str, TableSchema]
    foreign_keys: List[Tuple[str, str, str, str]]  # (table1, col1, table2, col2)


@dataclass
class MetaInfo:
    """提取的元信息"""
    KeyValues: List[str]
    CalcMode: str
    Aggregation: Optional[str] = None
    SubqueryTable: Optional[List[str]] = None
    OutputColumns: Optional[List[str]] = None
    GroupBy: Optional[List[str]] = None
    OrderBy: Optional[str] = None
    Limit: Optional[int] = None

    def to_text(self) -> str:
        """转换为标准文本格式"""
        lines = []
        if self.KeyValues:
            lines.append(f"KeyValues: {', '.join(self.KeyValues)}")
        lines.append(f"CalcMode: {self.CalcMode}")
        if self.Aggregation:
            lines.append(f"Aggregation: {self.Aggregation}")
        if self.SubqueryTable:
            lines.append(f"SubqueryTable: {', '.join(self.SubqueryTable)}")
        if self.OutputColumns:
            lines.append(f"OutputColumns: {', '.join(self.OutputColumns)}")
        if self.GroupBy:
            lines.append(f"GroupBy: {', '.join(self.GroupBy)}")
        if self.OrderBy:
            lines.append(f"OrderBy: {self.OrderBy}")
        if self.Limit:
            lines.append(f"Limit: {self.Limit}")
        return "\n".join(lines)


class SymbolicMetaExtractor:
    """纯符号化元信息提取器"""
    
    # ------------------------------
    # 符号规则定义
    # ------------------------------
    
    # CalcMode 关键词规则
    CALCMODE_PATTERNS = {
        "hypothetical_shift": [
            r"\bif\b", r"\bassume\b", r"\bassuming\b", r"\bsuppose\b", r"\b假设\b", r"\b假如\b"
        ],
        "conditional_sum": [
            r"\bif\b.*\bthen\b", r"\bconditional\b", r"\b根据条件\b", r"\b条件\b.*\b计算\b"
        ],
        "age_at_release": [
            r"\bage.*at.*release\b", r"\b发布.*年龄\b", r"\b发行.*年龄\b", r"\b歌曲.*发布.*年龄\b"
        ],
        "age_at_joined_event": [
            r"\bage.*at.*concert\b", r"\bage.*at.*event\b", r"\b音乐会.*年龄\b", r"\b活动.*年龄\b",
            r"\b参加.*年龄\b"
        ],
        "age_comparison": [
            r"\btwice.*age\b", r"\bage.*twice\b", r"\b年龄.*两倍\b", r"\b年龄.*比\b.*大\b"
        ],
        "ratio_comparison": [
            r"\btimes\b", r"\brate\b", r"\bratio\b", r"\b倍\b", r"\b比例\b"
        ],
        "years_since_event": [
            r"\byears.*since\b", r"\bsince.*years\b", r"\b距今.*年\b", r"\b多少.*年.*前\b",
            r"\bhow many years.*ago\b", r"\bhow many years.*since\b"
        ]
    }
    
    # Aggregation 关键词规则
    AGGREGATION_PATTERNS = {
        "count": [r"\bhow many\b", r"\bcount\b", r"\b统计\b", r"\b数量\b", r"\b多少\b.*个\b"],
        "sum": [r"\bsum\b", r"\btotal\b", r"\b求和\b", r"\b总\b.*数\b"],
        "avg": [r"\baverage\b", r"\bavg\b", r"\b平均\b"],
        "min": [r"\bminimum\b", r"\bmin\b", r"\bsmallest\b", r"\b最小\b", r"\b最早\b"],
        "max": [r"\bmaximum\b", r"\bmax\b", r"\blargest\b", r"\bbiggest\b", r"\bmost\b", r"\b最大\b", r"\b最多\b", r"\b最高\b"]
    }
    
    # OrderBy 关键词
    ORDERBY_PATTERNS = {
        "desc": [r"\border by.*desc\b", r"\bdescending\b", r"\b降序\b", r"\b从大到小\b", r"\b从高到低\b", r"\b最多\b", r"\b最高\b"],
        "asc": [r"\border by.*asc\b", r"\bascending\b", r"\b升序\b", r"\b从小到大\b", r"\b从低到高\b", r"\b最少\b", r"\b最低\b"]
    }
    
    # Limit 关键词
    LIMIT_PATTERNS = [
        r"\btop\s+(\d+)\b", r"\bfirst\s+(\d+)\b", r"\blimit\s+(\d+)\b", r"\b前\s*(\d+)\b"
    ]
    
    def __init__(self, db_base_path: Path = Path("BIRD/dev_20240627/dev_databases")):
        self.db_base_path = db_base_path
        self.schema_cache: Dict[str, DatabaseSchema] = {}
    
    def load_database_schema(self, db_id: str) -> DatabaseSchema:
        """加载数据库schema"""
        if db_id in self.schema_cache:
            return self.schema_cache[db_id]
        
        # 尝试查找数据库文件
        db_path = self.db_base_path / db_id / f"{db_id}.sqlite"
        if not db_path.exists():
            db_path = Path("..") / "spider" / "database" / db_id / f"{db_id}.sqlite"
        
        schema = DatabaseSchema(db_id=db_id, tables={}, foreign_keys=[])
        
        if db_path.exists():
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                
                # 获取所有表
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
                tables = [row[0] for row in cursor.fetchall()]
                
                for table in tables:
                    # 获取表的列
                    cursor.execute(f"PRAGMA table_info({table});")
                    columns = []
                    pk_col = None
                    for row in cursor.fetchall():
                        col_name = row[1]
                        columns.append(col_name)
                        if row[5] == 1:  # primary key
                            pk_col = col_name
                    schema.tables[table] = TableSchema(name=table, columns=columns, primary_key=pk_col)
                
                # 获取外键
                for table in tables:
                    cursor.execute(f"PRAGMA foreign_key_list({table});")
                    for row in cursor.fetchall():
                        schema.foreign_keys.append((table, row[3], row[2], row[4]))
                
                conn.close()
            except Exception as e:
                print(f"Warning: Could not load schema for {db_id}: {e}")
        
        # 从super_ontology补充schema
        self._augment_schema_from_ontology(schema)
        
        self.schema_cache[db_id] = schema
        return schema
    
    def _augment_schema_from_ontology(self, schema: DatabaseSchema):
        """从super_ontology补充schema信息"""
        ontology_path = Path("super_ontology.json")
        if not ontology_path.exists():
            return
        
        with open(ontology_path, "r", encoding="utf-8") as f:
            ontology = json.load(f)
        
        # 从概念补充
        for concept_name, concept_data in ontology.get("concepts", {}).items():
            sources = concept_data.get("sources", {})
            if schema.db_id in sources:
                source_data = sources[schema.db_id]
                table_name = source_data.get("table")
                slots = source_data.get("slots", {})
                
                if table_name:
                    if table_name not in schema.tables:
                        schema.tables[table_name] = TableSchema(name=table_name, columns=[])
                    # 补充列
                    for slot_name, col_name in slots.items():
                        if col_name not in schema.tables[table_name].columns:
                            schema.tables[table_name].columns.append(col_name)
    
    # ------------------------------
    # 符号提取器 - KeyValues
    # ------------------------------
    
    def extract_keyvalues(self, question: str) -> List[str]:
        """
        纯符号化提取KeyValues
        规则：
        1. 引号中的内容
        2. 数字（年份、金额等）
        3. 专有名词（通过关键词识别）
        """
        keyvalues = []
        question_lower = question.lower()
        
        # 1. 提取引号内容
        quoted_matches = re.findall(r'"([^"]+)"', question)
        quoted_matches += re.findall(r"'([^']+)'", question)
        keyvalues.extend(quoted_matches)
        
        # 2. 提取年份（4位数字）
        year_matches = re.findall(r'\b(19\d{2}|20\d{2})\b', question)
        for year in year_matches:
            if year not in keyvalues:
                keyvalues.append(year)
        
        # 3. 提取其他数字
        num_matches = re.findall(r'\b(\d+(?:\.\d+)?)\b', question)
        for num in num_matches:
            if num not in keyvalues and not (len(num) == 4 and num.isdigit()):  # 避免重复年份
                keyvalues.append(num)
        
        return keyvalues
    
    # ------------------------------
    # 符号提取器 - CalcMode
    # ------------------------------
    
    def extract_calcmode(self, question: str) -> str:
        """
        纯符号化识别CalcMode
        按优先级匹配
        """
        question_lower = question.lower()
        
        # 按优先级检查
        priority_order = [
            "hypothetical_shift",
            "conditional_sum",
            "age_at_release",
            "age_at_joined_event",
            "age_comparison",
            "ratio_comparison",
            "years_since_event"
        ]
        
        for mode in priority_order:
            patterns = self.CALCMODE_PATTERNS[mode]
            for pattern in patterns:
                if re.search(pattern, question_lower):
                    return mode
        
        return "none"
    
    # ------------------------------
    # 符号提取器 - Aggregation
    # ------------------------------
    
    def extract_aggregation(self, question: str) -> Optional[str]:
        """纯符号化识别Aggregation"""
        question_lower = question.lower()
        
        for agg_type, patterns in self.AGGREGATION_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, question_lower):
                    return agg_type
        
        return None
    
    # ------------------------------
    # 符号提取器 - SubqueryTable
    # ------------------------------
    
    def extract_subquerytable(self, question: str, schema: DatabaseSchema) -> List[str]:
        """
        纯符号化提取相关表
        规则：
        1. 问题中提到的表名
        2. 相关的概念匹配
        """
        tables = []
        question_lower = question.lower()
        
        # 1. 直接匹配表名
        for table_name in schema.tables.keys():
            if table_name.lower() in question_lower:
                if table_name not in tables:
                    tables.append(table_name)
        
        # 2. 匹配列名 -> 推断表
        for table_name, table_schema in schema.tables.items():
            for col_name in table_schema.columns:
                if col_name.lower() in question_lower:
                    if table_name not in tables:
                        tables.append(table_name)
                    break
        
        # 3. 从本体概念匹配
        tables = self._match_tables_from_ontology(question, schema, tables)
        
        return tables
    
    def _match_tables_from_ontology(self, question: str, schema: DatabaseSchema, current_tables: List[str]) -> List[str]:
        """从super_ontology匹配表"""
        ontology_path = Path("super_ontology.json")
        if not ontology_path.exists():
            return current_tables
        
        with open(ontology_path, "r", encoding="utf-8") as f:
            ontology = json.load(f)
        
        question_lower = question.lower()
        
        for concept_name, concept_data in ontology.get("concepts", {}).items():
            sources = concept_data.get("sources", {})
            if schema.db_id in sources:
                source_data = sources[schema.db_id]
                table_name = source_data.get("table")
                
                if table_name and table_name in schema.tables:
                    # 检查概念名是否在问题中
                    if concept_name.lower() in question_lower:
                        if table_name not in current_tables:
                            current_tables.append(table_name)
                    # 检查槽名
                    slots = source_data.get("slots", {})
                    for slot_name in slots.keys():
                        if slot_name.lower() in question_lower:
                            if table_name not in current_tables:
                                current_tables.append(table_name)
                            break
        
        return current_tables
    
    # ------------------------------
    # 符号提取器 - OutputColumns
    # ------------------------------
    
    def extract_outputcolumns(self, question: str, schema: DatabaseSchema, tables: List[str]) -> List[str]:
        """纯符号化提取输出列"""
        columns = []
        question_lower = question.lower()
        
        for table_name in tables:
            if table_name not in schema.tables:
                continue
            table_schema = schema.tables[table_name]
            
            for col_name in table_schema.columns:
                if col_name.lower() in question_lower:
                    if col_name not in columns:
                        columns.append(col_name)
        
        # 如果没有找到列，返回该表的常见列
        if not columns and tables:
            for table_name in tables:
                if table_name in schema.tables:
                    table_schema = schema.tables[table_name]
                    # 找常见的名字列
                    common_cols = ["name", "title", "id", "number", "code"]
                    for col in common_cols:
                        for table_col in table_schema.columns:
                            if col.lower() in table_col.lower():
                                if table_col not in columns:
                                    columns.append(table_col)
        
        return columns
    
    # ------------------------------
    # 符号提取器 - Limit
    # ------------------------------
    
    def extract_limit(self, question: str) -> Optional[int]:
        """纯符号化提取Limit"""
        for pattern in self.LIMIT_PATTERNS:
            match = re.search(pattern, question.lower())
            if match:
                return int(match.group(1))
        return None
    
    # ------------------------------
    # 主提取函数
    # ------------------------------
    
    def extract(self, question: str, db_id: str) -> MetaInfo:
        """
        完整的元信息提取
        """
        # 加载schema
        schema = self.load_database_schema(db_id)
        
        # 逐个提取
        keyvalues = self.extract_keyvalues(question)
        calcmode = self.extract_calcmode(question)
        aggregation = self.extract_aggregation(question)
        subquerytable = self.extract_subquerytable(question, schema)
        outputcolumns = self.extract_outputcolumns(question, schema, subquerytable)
        limit = self.extract_limit(question)
        
        return MetaInfo(
            KeyValues=keyvalues,
            CalcMode=calcmode,
            Aggregation=aggregation,
            SubqueryTable=subquerytable if subquerytable else None,
            OutputColumns=outputcolumns if outputcolumns else None,
            Limit=limit
        )


def parse_gold_meta(output_text: str) -> MetaInfo:
    """解析标准答案的元信息"""
    kv = []
    calcmode = "none"
    agg = None
    tables = None
    cols = None
    
    for line in output_text.strip().split("\n"):
        line = line.strip()
        if line.startswith("KeyValues:"):
            kv_str = line[len("KeyValues:"):].strip()
            if kv_str:
                kv = [x.strip() for x in kv_str.split(",")]
        elif line.startswith("CalcMode:"):
            calcmode = line[len("CalcMode:"):].strip()
        elif line.startswith("Aggregation:"):
            agg = line[len("Aggregation:"):].strip()
        elif line.startswith("SubqueryTable:"):
            tables_str = line[len("SubqueryTable:"):].strip()
            if tables_str:
                tables = [x.strip() for x in tables_str.split(",")]
        elif line.startswith("OutputColumns:"):
            cols_str = line[len("OutputColumns:"):].strip()
            if cols_str:
                cols = [x.strip() for x in cols_str.split(",")]
    
    return MetaInfo(
        KeyValues=kv,
        CalcMode=calcmode,
        Aggregation=agg,
        SubqueryTable=tables,
        OutputColumns=cols
    )


def compare_meta(pred: MetaInfo, gold: MetaInfo) -> Dict[str, Any]:
    """比较预测和标准答案，计算准确率"""
    results = {
        "KeyValues": set(pred.KeyValues) == set(gold.KeyValues),
        "CalcMode": pred.CalcMode == gold.CalcMode,
        "Aggregation": pred.Aggregation == gold.Aggregation,
        "SubqueryTable": (set(pred.SubqueryTable) == set(gold.SubqueryTable)) if (pred.SubqueryTable and gold.SubqueryTable) else (pred.SubqueryTable == gold.SubqueryTable),
        "OutputColumns": (set(pred.OutputColumns) == set(gold.OutputColumns)) if (pred.OutputColumns and gold.OutputColumns) else (pred.OutputColumns == gold.OutputColumns)
    }
    
    results["overall"] = all(results.values())
    return results


def test_on_spider_data():
    """在spider数据集上测试"""
    print("=" * 80)
    print("纯符号化元信息提取器 - Spider数据集测试")
    print("=" * 80)
    
    # 加载训练数据
    data_path = Path("data/spider_train_reverse.jsonl")
    if not data_path.exists():
        print(f"数据文件不存在: {data_path}")
        return
    
    extractor = SymbolicMetaExtractor()
    
    total = 0
    correct = 0
    field_stats = {
        "KeyValues": 0,
        "CalcMode": 0,
        "Aggregation": 0,
        "SubqueryTable": 0,
        "OutputColumns": 0
    }
    
    with open(data_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            
            item = json.loads(line)
            
            # 解析输入
            input_text = item["input"]
            question = input_text.replace("问题：", "").replace("证据：", "").strip()
            db_id = item["db_id"]
            
            # 解析标准答案
            gold_meta = parse_gold_meta(item["output"])
            
            # 预测
            try:
                pred_meta = extractor.extract(question, db_id)
            except Exception as e:
                print(f"Error processing {db_id}: {e}")
                continue
            
            # 比较
            comp = compare_meta(pred_meta, gold_meta)
            
            total += 1
            if comp["overall"]:
                correct += 1
            
            for field, is_correct in comp.items():
                if field != "overall" and is_correct:
                    field_stats[field] += 1
            
            # 打印前几个例子
            if total <= 5:
                print(f"\n--- Example {total} ---")
                print(f"Question: {question}")
                print(f"DB: {db_id}")
                print(f"\nGold:\n{item['output']}")
                print(f"\nPred:\n{pred_meta.to_text()}")
                print(f"\nMatch: {comp['overall']}")
                print(f"Fields: {comp}")
    
    # 统计
    print("\n" + "=" * 80)
    print("测试结果统计")
    print("=" * 80)
    print(f"Total examples: {total}")
    print(f"Overall accuracy: {correct / total * 100:.1f}% ({correct}/{total})")
    
    for field, count in field_stats.items():
        print(f"{field}: {count / total * 100:.1f}% ({count}/{total})")


if __name__ == "__main__":
    test_on_spider_data()
