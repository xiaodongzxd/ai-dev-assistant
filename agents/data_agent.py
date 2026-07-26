"""
Data Agent：模拟自动驾驶数据处理、标注质量检查、长尾场景挖掘。
支持动态清洗规则、物理一致性校验、脱敏预处理及数据版本控制。
"""

import datetime
import hashlib
import json
from typing import Dict, Any, List, Optional

import numpy as np
import pandas as pd
from loguru import logger

from llm.ollama_client import get_llm_client
from tools.file_tools import get_file_system
from utils.sanitize import ConfigurableMasker, MaskLevel


class DataAgent:
    def __init__(self):
        self.llm = get_llm_client()
        self.fs = get_file_system()
        # 初始化脱敏引擎（全局单例）
        self.masker = ConfigurableMasker()

    # ============================================================
    # 1. 数据清洗（支持 config 字典 + 独立关键字参数）
    # ============================================================
    def clean_dataset(
            self,
            df: pd.DataFrame,
            config: Optional[Dict] = None,
            *,
            method: Optional[str] = None,
            std_threshold: Optional[float] = None,
            iqr_multiplier: Optional[float] = None,
            enable_physical_check: Optional[bool] = None,
    ) -> pd.DataFrame:
        """
        数据清洗：去重、填充缺失值、异常值截断。

        参数优先级：显式关键字参数 > config 字典 > 默认值。

        Args:
            df: 待清洗的 DataFrame
            config: 可选配置字典，键值：
                - method: 'std' 或 'iqr'
                - std_threshold: 标准差倍数（默认 3）
                - iqr_multiplier: IQR 倍数（默认 1.5）
                - enable_physical_check: 是否启用物理一致性校验（默认 True）
            method: 清洗方法（'std' 或 'iqr'），优先级高于 config
            std_threshold: 标准差倍数，优先级高于 config
            iqr_multiplier: IQR 倍数，优先级高于 config
            enable_physical_check: 是否启用物理校验，优先级高于 config

        Returns:
            清洗后的 DataFrame
        """
        # ---------- 参数解析（优先级：显式传参 > config > 默认值） ----------
        cfg = config or {}

        _method = method or cfg.get('method', 'std')
        _std_threshold = std_threshold if std_threshold is not None else cfg.get('std_threshold', 3)
        _iqr_multiplier = iqr_multiplier if iqr_multiplier is not None else cfg.get('iqr_multiplier', 1.5)
        _enable_physical_check = (
            enable_physical_check
            if enable_physical_check is not None
            else cfg.get('enable_physical_check', True)
        )

        logger.info(
            f"Cleaning dataset: {df.shape[0]} rows, {df.shape[1]} cols, "
            f"method={_method}, std_threshold={_std_threshold}, "
            f"iqr_multiplier={_iqr_multiplier}, physical_check={_enable_physical_check}"
        )

        # ---------- 1. 去重 ----------
        df = df.drop_duplicates()

        # ---------- 2. 填充缺失值 ----------
        for col in df.columns:
            if pd.api.types.is_numeric_dtype(df[col]):
                df[col] = df[col].fillna(df[col].median())
            else:
                mode_val = df[col].mode()
                df[col] = df[col].fillna(mode_val[0] if not mode_val.empty else "unknown")

        # ---------- 3. 异常值截断 ----------
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        for col in numeric_cols:
            if _method == 'iqr':
                Q1 = df[col].quantile(0.25)
                Q3 = df[col].quantile(0.75)
                IQR = Q3 - Q1
                lower = Q1 - _iqr_multiplier * IQR
                upper = Q3 + _iqr_multiplier * IQR
            else:  # 'std'
                mean = df[col].mean()
                std = df[col].std()
                lower = mean - _std_threshold * std
                upper = mean + _std_threshold * std
            df[col] = df[col].clip(lower, upper)

        # ---------- 4. 物理一致性校验 ----------
        if _enable_physical_check and 'speed_kmh' in df.columns and 'acceleration' in df.columns:
            df = self._validate_physical_consistency(df)

        logger.info(f"Cleaning done. New shape: {df.shape}")
        return df

    def _validate_physical_consistency(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        物理规则校验：剔除速度与加速度逻辑冲突的行。
        示例规则：速度 < 5 km/h 且加速度 < -3 m/s² 视为不合理（静止时不应猛踩刹车）。
        """
        mask = ~((df['speed_kmh'] < 5) & (df['acceleration'] < -3))
        removed = df.shape[0] - mask.sum()
        if removed > 0:
            logger.info(f"Removed {removed} rows due to physical consistency check.")
        return df[mask].copy()

    # ============================================================
    # 2. 数据脱敏（内部辅助）
    # ============================================================
    def _sanitize_text(
            self,
            text: str,
            level: str = "medium",
            audit: bool = False
    ) -> str:
        """
        脱敏封装：支持指定级别（low / medium / high）。

        Args:
            text: 原始文本
            level: 脱敏级别
            audit: 是否记录详细审计日志

        Returns:
            脱敏后文本
        """
        mask_level = MaskLevel.from_string(level)
        masked_text, audit_log = self.masker.mask(
            text,
            level=mask_level,
            keep_domain_for_email=True,
            audit=audit
        )
        if audit_log:
            logger.debug(f"Mask audit: {audit_log}")
        return masked_text

    # ============================================================
    # 3. 标注质量检查（支持分层抽样）
    # ============================================================
    def check_label_quality(
            self,
            df: pd.DataFrame,
            label_column: str,
            text_column: str,
            sample_size: int = 5
    ) -> Dict[str, Any]:
        """
        随机抽样，用 LLM 判断标注是否与文本一致。
        当 sample_size 较大时自动启用分层抽样（保证各标签类别均有覆盖）。
        """
        if len(df) == 0:
            return {
                "sample_size": 0,
                "inconsistent_count": 0,
                "quality_score": 1.0,
                "inconsistent_samples": []
            }

        actual_sample_size = min(sample_size, len(df))

        # 如果标签列存在且样本数足够，启用分层抽样
        use_stratify = (
                label_column in df.columns
                and actual_sample_size >= 3
                and len(df[label_column].value_counts()) > 1
        )

        if use_stratify:
            label_counts = df[label_column].value_counts()
            num_classes = len(label_counts)
            if num_classes <= actual_sample_size:
                sample_per_class = (label_counts / len(df) * actual_sample_size).round().astype(int)
                sample_per_class = sample_per_class.clip(lower=1)
                while sample_per_class.sum() < actual_sample_size:
                    sample_per_class.iloc[0] += 1
                sampled_indices = []
                for label, n in sample_per_class.items():
                    class_df = df[df[label_column] == label]
                    if len(class_df) > 0:
                        n = min(n, len(class_df))
                        sampled_indices.extend(class_df.sample(n=n, random_state=42).index.tolist())
                sample = df.loc[sampled_indices]
            else:
                sample = df.sample(n=actual_sample_size, random_state=42)
        else:
            sample = df.sample(n=actual_sample_size, random_state=42)

        inconsistent = []
        for idx, row in sample.iterrows():
            text = str(row[text_column])
            label = str(row[label_column])
            safe_text = self._sanitize_text(text)

            prompt = f"Text: {safe_text}\nLabel: {label}\nAnswer only 'yes' or 'no': does the label match?"
            response = self.llm.generate(prompt).strip().lower()

            if "no" in response:
                inconsistent.append({
                    "text": text,
                    "label": label,
                    "index": int(idx)
                })

        quality_score = 1.0 - (len(inconsistent) / len(sample)) if len(sample) > 0 else 1.0

        return {
            "sample_size": len(sample),
            "inconsistent_count": len(inconsistent),
            "quality_score": quality_score,
            "inconsistent_samples": inconsistent[:3]
        }

    # ============================================================
    # 4. 长尾场景挖掘
    # ============================================================
    def mine_long_tail_scenes(self, descriptions: List[str], top_k: int = 5) -> List[str]:
        """
        使用 TF-IDF 找出罕见文本（模长最大的几条）作为长尾场景。
        先对描述去重，再计算 TF-IDF 向量模长，取模长最大的 top_k。
        """
        from sklearn.feature_extraction.text import TfidfVectorizer

        if len(descriptions) < 3:
            return ["insufficient data for mining"]

        unique_descs = list(set([str(d) for d in descriptions if d]))
        if len(unique_descs) < 3:
            return unique_descs[:top_k]

        vectorizer = TfidfVectorizer(max_features=100, stop_words='english')
        X = vectorizer.fit_transform(unique_descs)
        norms = np.linalg.norm(X.toarray(), axis=1)

        rare_indices = np.argsort(norms)[-top_k:]
        return [unique_descs[i] for i in rare_indices if i < len(unique_descs)]

    # ============================================================
    # 5. 主入口
    # ============================================================
    def process_data_request(
            self,
            user_request: str,
            data_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        主入口：生成模拟数据或读取 CSV → 清洗 → 质量检查 → 长尾挖掘 → 保存。
        返回结果中 cleaned_data_path 保持原路径（向后兼容），同时生成带版本号的副本。
        """
        version_id = hashlib.md5(
            f"{datetime.datetime.now().isoformat()}{user_request}".encode()
        ).hexdigest()[:8]

        if data_path is None or not self.fs.file_exists(data_path):
            logger.info("No data provided, generating synthetic dataset for demo")
            df = self._generate_synthetic_driving_data(100)
            source = "synthetic"
        else:
            content = self.fs.read_file(data_path)
            import io
            df = pd.read_csv(io.StringIO(content))
            source = "file"
            logger.info(f"Loaded data from {data_path}, {len(df)} rows")

        if "description" in df.columns:
            df["description"] = df["description"].astype(str).apply(self._sanitize_text)

        cleaned_df = self.clean_dataset(df)

        quality_report = None
        if "label" in cleaned_df.columns and "description" in cleaned_df.columns:
            quality_report = self.check_label_quality(
                cleaned_df,
                label_column="label",
                text_column="description",
                sample_size=10
            )

        long_tail_scenes = []
        if "description" in cleaned_df.columns and len(cleaned_df) > 5:
            desc_list = cleaned_df["description"].dropna().astype(str).tolist()
            if desc_list:
                long_tail_scenes = self.mine_long_tail_scenes(desc_list, top_k=5)

        output_path = "/data/cleaned_dataset.csv"
        self.fs.write_file(output_path, cleaned_df.to_csv(index=False))

        versioned_path = f"/data/cleaned_dataset_{version_id}.csv"
        self.fs.write_file(versioned_path, cleaned_df.to_csv(index=False))

        metadata = {
            "version_id": version_id,
            "source": source,
            "original_rows": len(df),
            "cleaned_rows": len(cleaned_df),
            "timestamp": datetime.datetime.now().isoformat(),
            "user_request": user_request,
            "cleaned_data_path": versioned_path
        }
        metadata_path = f"/data/metadata_{version_id}.json"
        self.fs.write_file(metadata_path, json.dumps(metadata, indent=2))

        logger.info(f"Data processing completed. Version: {version_id}")

        return {
            "status": "success",
            "original_shape": df.shape,
            "cleaned_shape": cleaned_df.shape,
            "quality_report": quality_report,
            "long_tail_scenes": long_tail_scenes,
            "cleaned_data_path": output_path,
            "version_id": version_id,
            "sample_rows": cleaned_df.head(3).to_dict(orient="records")
        }

    # ============================================================
    # 6. 模拟数据生成
    # ============================================================
    def _generate_synthetic_driving_data(self, n: int) -> pd.DataFrame:
        """生成模拟驾驶场景数据，包含 description、label 及传感器数值列。"""
        np.random.seed(42)
        scenes = [
            "highway at night with light rain",
            "urban intersection with pedestrians crossing",
            "parking lot with children playing",
            "construction zone with temporary signs",
            "school zone during drop-off hours",
            "tunnel with sudden brightness change",
            "sharp curve on mountain road",
            "emergency vehicle approaching from behind",
            "snow-covered road with unclear lane markings",
            "roundabout with heavy traffic",
            "narrow residential street with parked cars",
            "bridge with strong crosswind"
        ]
        labels = [
            "normal", "caution", "caution", "slow_down", "slow_down",
            "caution", "slow_down", "pull_over", "hazard", "normal",
            "caution", "caution"
        ]
        descriptions = np.random.choice(scenes, n)
        label_map = dict(zip(scenes, labels))
        generated_labels = [label_map[desc] for desc in descriptions]

        if n > 10:
            error_indices = np.random.choice(n, size=int(n * 0.05), replace=False)
            other_labels = list(set(labels))
            for idx in error_indices:
                current = generated_labels[idx]
                others = [l for l in other_labels if l != current]
                generated_labels[idx] = np.random.choice(others)

        df = pd.DataFrame({
            "description": descriptions,
            "label": generated_labels,
            "timestamp": pd.date_range("2025-01-01", periods=n, freq="h"),
            "speed_kmh": np.random.uniform(0, 120, n),
            "acceleration": np.random.uniform(-5, 5, n),
            "steering_angle": np.random.uniform(-45, 45, n)
        })
        return df


# ============================================================
# 全局单例
# ============================================================
_data_agent = None


def get_data_agent() -> DataAgent:
    global _data_agent
    if _data_agent is None:
        _data_agent = DataAgent()
    return _data_agent
