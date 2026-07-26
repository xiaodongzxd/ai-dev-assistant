import json
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any

from loguru import logger


class MaskLevel(Enum):
    """脱敏强度级别"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    @classmethod
    def from_string(cls, value: str) -> "MaskLevel":
        try:
            return cls(value.lower())
        except ValueError:
            return cls.MEDIUM


@dataclass
class SanitizeRule:
    """脱敏规则（从 JSON 加载）"""
    id: str
    name: str
    level: str  # 'low', 'medium', 'high'
    pattern: str  # 原始正则字符串
    replacement: str
    description: str
    preserve_domain: bool = False  # 仅对邮箱有效
    enabled: bool = True
    compiled: Optional[re.Pattern] = field(default=None, init=False)

    def compile(self):
        """编译正则，支持边界检查"""
        flags = re.UNICODE
        self.compiled = re.compile(self.pattern, flags)


class ConfigurableMasker:
    """
    可配置、可分级、可扩展的敏感数据脱敏引擎。
    """

    def __init__(self, config_path: Optional[str] = None):
        # 加载配置
        if config_path is None:
            config_path = str(Path(__file__).parent.parent / "config" / "sanitize_rules.json")

        self.config = self._load_config(config_path)
        self.level_map = self.config.get("levels", {})

        # 加载并编译规则
        self.rules: List[SanitizeRule] = []
        for rule_data in self.config.get("rules", []):
            if not rule_data.get("enabled", True):
                continue
            rule = SanitizeRule(
                id=rule_data["id"],
                name=rule_data["name"],
                level=rule_data.get("level", "medium"),
                pattern=rule_data["pattern"],
                replacement=rule_data["replacement"],
                description=rule_data.get("description", ""),
                preserve_domain=rule_data.get("preserve_domain", False),
            )
            rule.compile()
            self.rules.append(rule)

        logger.info(f"Masker initialized with {len(self.rules)} rules, levels: {list(self.level_map.keys())}")

    def _load_config(self, path: str) -> Dict[str, Any]:
        """加载 JSON 配置，如果文件不存在则使用内置默认配置"""
        path = str(path)
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            logger.warning(f"Config file not found: {path}, using built-in defaults")
            return self._get_default_config()
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON config: {e}, using built-in defaults")
            return self._get_default_config()

    def _get_default_config(self) -> Dict[str, Any]:
        """内置默认配置（与上面 JSON 内容一致）"""
        # 实际生产环境可以用一个内联字典兜底
        # 此处为简洁，直接返回一个最小可用配置
        return {
            "levels": {
                "low": ["手机号", "身份证"],
                "medium": ["手机号", "身份证", "车牌", "军官证", "邮箱"],
                "high": ["手机号", "身份证", "车牌", "军官证", "邮箱", "座机", "银行卡", "护照"]
            },
            "rules": [
                {
                    "id": "phone", "name": "手机号", "level": "low",
                    "pattern": "(?<!\\d)1[3-9]\\d{9}(?!\\d)",
                    "replacement": "[PHONE]", "description": "中国手机号（11位）"
                },
                {
                    "id": "id_card", "name": "身份证", "level": "low",
                    "pattern": "\\b[1-9]\\d{5}(18|19|20)\\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\\d|3[01])\\d{3}[\\dXx]\\b",
                    "replacement": "[ID_CARD]", "description": "18位身份证号"
                },
                {
                    "id": "plate", "name": "车牌", "level": "medium",
                    "pattern": "(?:[京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼][A-Z][A-Z0-9]{5,6}|WJ[·]?[A-Z0-9]{5,6}|[京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼][·]?[A-Z][A-Z0-9]{4,5}[警领应])",
                    "replacement": "[PLATE]", "description": "中国车牌（含军警领应）"
                },
                {
                    "id": "military", "name": "军官证", "level": "medium",
                    "pattern": "[军空海陆][·]?\\d{8,9}",
                    "replacement": "[MILITARY_ID]", "description": "军官证号"
                },
                {
                    "id": "email", "name": "邮箱", "level": "medium",
                    "pattern": "\\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Z|a-z]{2,}\\b",
                    "replacement": "[EMAIL]", "description": "电子邮箱",
                    "preserve_domain": True
                },
                {
                    "id": "landline", "name": "座机", "level": "high",
                    "pattern": "(?<!\\d)(0\\d{2,3}-?\\d{7,8})(?!\\d)",
                    "replacement": "[LANDLINE]", "description": "固定电话（含区号）"
                },
                {
                    "id": "bank_card", "name": "银行卡", "level": "high",
                    "pattern": "\\b[1-9]\\d{15,18}\\b",
                    "replacement": "[BANK_CARD]", "description": "银行卡号（16~19位）"
                },
                {
                    "id": "passport", "name": "护照", "level": "high",
                    "pattern": "\\b[Ee][1-9]\\d{7}\\b",
                    "replacement": "[PASSPORT]", "description": "护照号"
                }
            ]
        }

    def get_rules_for_level(self, level: MaskLevel) -> List[SanitizeRule]:
        """根据级别过滤规则"""
        level_name = level.value
        # 从配置的 level_map 中获取该级别包含的规则名称列表
        allowed_names = self.level_map.get(level_name, [])
        return [
            rule for rule in self.rules
            if rule.name in allowed_names and rule.enabled
        ]

    def mask(
            self,
            text: str,
            level: MaskLevel = MaskLevel.MEDIUM,
            keep_domain_for_email: bool = True,
            audit: bool = False
    ) -> Tuple[str, List[str]]:
        """
        对文本进行分级脱敏。

        Args:
            text: 待脱敏文本
            level: 脱敏强度（LOW / MEDIUM / HIGH）
            keep_domain_for_email: 是否保留邮箱域名（如 ***@gmail.com）
            audit: 是否返回审计日志

        Returns:
            (脱敏后的文本, 审计日志列表)
        """
        if not isinstance(text, str):
            return str(text), []

        audit_log = []
        masked_text = text
        rules = self.get_rules_for_level(level)

        for rule in rules:
            if not rule.compiled:
                continue

            # 检查是否匹配
            if rule.compiled.search(masked_text):
                if audit:
                    audit_log.append(
                        f"[{level.value.upper()}] {rule.description} -> {rule.replacement}"
                    )

                # 特殊处理：邮箱保留域名
                if rule.preserve_domain and keep_domain_for_email:
                    masked_text = self._mask_email_preserve_domain(masked_text, rule.compiled)
                else:
                    masked_text = rule.compiled.sub(rule.replacement, masked_text)

        return masked_text, audit_log

    def _mask_email_preserve_domain(self, text: str, pattern: re.Pattern) -> str:
        """替换邮箱用户名，保留 @domain.com"""

        def replace_email(match):
            full = match.group(0)
            at_index = full.find('@')
            if at_index > 0:
                return f'[EMAIL]{full[at_index:]}'
            return '[EMAIL]'

        return pattern.sub(replace_email, text)

    def mask_batch(
            self,
            texts: List[str],
            level: MaskLevel = MaskLevel.MEDIUM,
            keep_domain_for_email: bool = True,
            audit: bool = False
    ) -> List[Tuple[str, List[str]]]:
        """批量脱敏（复用已编译规则）"""
        return [
            self.mask(t, level, keep_domain_for_email, audit)
            for t in texts
        ]
