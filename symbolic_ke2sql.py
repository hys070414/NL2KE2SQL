#!/usr/bin/env python3
"""
纯符号化 KE2SQL 转换器
完全基于本体和规则实现从 Knowledge Equation 到 SQL 的转换，无需 LLM
"""

import re
import json
import os
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class AbstractKE:
    """抽象的知识方程（本体映射结果）"""
    concepts: List[str] = field(default_factory=list)
    operators: List[str] = field(default_factory=list)
    db_id: str = ""


@dataclass  
class KEDetails:
    """KE的细节（元信息提取结果）"""
    KeyValues: List[str] = field(default_factory=list)
    CalcMode: str = "none"
    Aggregation: Optional[str] = None
    Filter: List[str] = field(default_factory=list)
    OrderBy: Optional[str] = None
    Limit: Optional[int] = None
    Keywords: List[str] = field(default_factory=list)


class SymbolicKE2SQL:
    """
    纯符号化 KE2SQL 转换器
    
    核心流程：
    1. 解析抽象 KE（概念 + 运算符）
    2. 从本体获取表/列映射
    3. 结合元信息构建 SQL
    4. 应用过滤、排序、聚合等规则
    """
    
    def __init__(self, ontology_path: str = "super_ontology.json"):
        self.ontology = None
        self.concepts = {}
        self.links = {}
        
        if os.path.exists(ontology_path):
            try:
                with open(ontology_path, 'r', encoding='utf-8') as f:
                    self.ontology = json.load(f)
                    if 'concepts' in self.ontology:
                        self.concepts = self.ontology['concepts']
                        for name, concept in self.ontology['concepts'].items():
                            if concept.get('type') == 'LINK':
                                self.links[name] = concept
            except Exception as e:
                print(f"警告：无法加载本体文件 {ontology_path}: {e}")
    
    def get_table_for_concept(self, concept_name: str, db_id: str = None) -> Optional[str]:
        """获取概念对应的数据库表"""
        if concept_name not in self.concepts:
            return None
        
        concept_info = self.concepts[concept_name]
        if 'sources' in concept_info:
            for source_name, source_info in concept_info['sources'].items():
                if db_id and source_info.get('database') != db_id:
                    continue
                return source_info.get('table')
        return None
    
    def get_columns_for_concept(self, concept_name: str, db_id: str = None) -> Dict[str, str]:
        """获取概念对应的数据库列（slot -> column）"""
        slots = {}
        if concept_name not in self.concepts:
            return slots
        
        concept_info = self.concepts[concept_name]
        if 'sources' in concept_info:
            for source_name, source_info in concept_info['sources'].items():
                if db_id and source_info.get('database') != db_id:
                    continue
                if 'slots' in source_info:
                    slots.update(source_info['slots'])
                    break
        return slots
    
    def map_aggregation(self, agg_type: str) -> str:
        """映射聚合函数"""
        agg_map = {
            'count': 'COUNT(*)',
            'sum': 'SUM({column})',
            'avg': 'AVG({column})',
            'max': 'MAX({column})',
            'min': 'MIN({column})'
        }
        return agg_map.get(agg_type, '')
    
    def build_select_clause(self, ke_details: KEDetails, columns: Dict[str, str]) -> str:
        """构建 SELECT 子句"""
        if ke_details.Aggregation:
            agg_func = self.map_aggregation(ke_details.Aggregation)
            if agg_func == 'COUNT(*)':
                return agg_func
            # 使用第一个数值列
            for slot, column in columns.items():
                if any(keyword in slot.lower() for keyword in ['id', 'count', 'number', 'amount', 'score', 'rate']):
                    return agg_func.format(column=column)
            # 默认使用第一个列
            first_column = list(columns.values())[0] if columns else '*'
            return agg_func.format(column=first_column)
        return ', '.join(columns.values()) if columns else '*'
    
    def build_where_clause(self, ke_details: KEDetails, columns: Dict[str, str]) -> str:
        """构建 WHERE 子句"""
        conditions = []
        
        # 添加 KeyValues 条件
        if ke_details.KeyValues:
            # 找到数值列
            numeric_columns = [col for slot, col in columns.items() 
                              if any(keyword in slot.lower() for keyword in ['id', 'score', 'rate', 'age', 'year'])]
            if numeric_columns and ke_details.KeyValues:
                # 简单策略：将数值与第一个数值列匹配
                for value in ke_details.KeyValues:
                    if value.isdigit():
                        conditions.append(f"{numeric_columns[0]} = {value}")
        
        # 添加比较条件
        if 'comparison' in ke_details.Keywords and ke_details.KeyValues:
            numeric_columns = [col for slot, col in columns.items() 
                              if any(keyword in slot.lower() for keyword in ['score', 'rate', 'age'])]
            if numeric_columns and ke_details.KeyValues:
                for value in ke_details.KeyValues:
                    if value.isdigit():
                        conditions.append(f"{numeric_columns[0]} > {value}")
        
        if conditions:
            return "WHERE " + " AND ".join(conditions)
        return ""
    
    def build_order_clause(self, ke_details: KEDetails, columns: Dict[str, str]) -> str:
        """构建 ORDER BY 子句"""
        if ke_details.OrderBy:
            # 使用第一个数值列
            numeric_columns = [col for slot, col in columns.items() 
                              if any(keyword in slot.lower() for keyword in ['id', 'score', 'rate', 'age'])]
            if numeric_columns:
                return f"ORDER BY {numeric_columns[0]} {ke_details.OrderBy}"
        return ""
    
    def build_limit_clause(self, ke_details: KEDetails) -> str:
        """构建 LIMIT 子句"""
        if ke_details.Limit:
            return f"LIMIT {ke_details.Limit}"
        return ""
    
    def convert(self, abstract_ke: AbstractKE, ke_details: KEDetails) -> str:
        """
        将 KE 转换为 SQL
        
        :param abstract_ke: 抽象知识方程（概念 + 运算符）
        :param ke_details: KE 细节（元信息）
        :return: 生成的 SQL
        """
        if not abstract_ke.concepts:
            return ""
        
        # 获取主概念对应的表和列
        main_concept = abstract_ke.concepts[0]
        table = self.get_table_for_concept(main_concept, abstract_ke.db_id)
        if not table:
            return f"-- 未找到概念 '{main_concept}' 对应的表"
        
        columns = self.get_columns_for_concept(main_concept, abstract_ke.db_id)
        
        # 构建 SQL 各部分
        select_clause = self.build_select_clause(ke_details, columns)
        where_clause = self.build_where_clause(ke_details, columns)
        order_clause = self.build_order_clause(ke_details, columns)
        limit_clause = self.build_limit_clause(ke_details)
        
        # 组合 SQL
        sql_parts = [
            f"SELECT {select_clause}",
            f"FROM {table}"
        ]
        
        if where_clause:
            sql_parts.append(where_clause)
        if order_clause:
            sql_parts.append(order_clause)
        if limit_clause:
            sql_parts.append(limit_clause)
        
        return " ".join(sql_parts)


def demo():
    """演示纯符号化 KE2SQL"""
    print("=" * 80)
    print("纯符号化 KE2SQL 转换器演示")
    print("=" * 80)
    
    # 初始化转换器
    ke2sql = SymbolicKE2SQL()
    print(f"本体概念数: {len(ke2sql.concepts)}")
    
    # 测试案例1：K-12学生最高免费率
    print("\n[案例1] K-12学生最高免费率")
    abstract_ke = AbstractKE(
        concepts=['School', 'Student'],
        operators=['max'],
        db_id='california_schools'
    )
    ke_details = KEDetails(
        KeyValues=[],
        Aggregation='max',
        OrderBy='DESC'
    )
    sql = ke2sql.convert(abstract_ke, ke_details)
    print(f"KE: {abstract_ke.concepts} + {abstract_ke.operators}")
    print(f"元信息: Aggregation={ke_details.Aggregation}, OrderBy={ke_details.OrderBy}")
    print(f"SQL: {sql}")
    
    # 测试案例2：超过400分的学生数
    print("\n[案例2] 超过400分的学生数")
    abstract_ke = AbstractKE(
        concepts=['Student'],
        operators=['count'],
        db_id='california_schools'
    )
    ke_details = KEDetails(
        KeyValues=['400'],
        Aggregation='count',
        Keywords=['comparison']
    )
    sql = ke2sql.convert(abstract_ke, ke_details)
    print(f"KE: {abstract_ke.concepts} + {abstract_ke.operators}")
    print(f"元信息: Aggregation={ke_details.Aggregation}, KeyValues={ke_details.KeyValues}")
    print(f"SQL: {sql}")


if __name__ == "__main__":
    demo()