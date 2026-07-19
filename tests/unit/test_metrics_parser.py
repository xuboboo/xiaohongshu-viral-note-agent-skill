"""operations/post_publish.py 指标解析纯函数单测。

覆盖：
- 标签邻近策略（中文连续文本）
- KV 策略（结构化 key:value）
- 万/k 后缀解析
- 全 null 诊断
- 自定义标签别名
"""
import pytest

from xhs_skill.operations.post_publish import (
    MetricParseResult,
    parse_number,
    parse_published_metrics,
)


class TestParseNumber:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("1.2万", 12000),
            ("3k", 3000),
            ("1,234", 1234),
            ("500", 500),
            ("2.5万", 25000),
            ("1亿", 100_000_000),
            ("3.5w", 35000),
            ("", None),
            ("abc", None),
        ],
    )
    def test_parse_number(self, raw: str, expected: int | None):
        assert parse_number(raw) == expected


class TestParsePublishedMetrics:
    def test_label_adjacent_strategy_basic(self):
        """原始场景：标签后紧跟数字。"""
        text = "观看 1.2万\n点赞 328\n收藏 56\n评论 12\n分享 3"
        result = parse_published_metrics(text)
        assert result.values["views"] == 12000
        assert result.values["likes"] == 328
        assert result.values["saves"] == 56
        assert result.values["comments"] == 12
        assert result.values["shares"] == 3
        assert result.strategy_used in ("kv", "label_adjacent")
        assert result.text_length == len(text)

    def test_kv_strategy_colon_format(self):
        """结构化格式：观看：1200。"""
        text = "观看：1200\n点赞：300\n收藏：45\n评论：8"
        result = parse_published_metrics(text)
        assert result.values["views"] == 1200
        assert result.values["likes"] == 300
        assert result.values["saves"] == 45
        assert result.values["comments"] == 8

    def test_wan_suffix(self):
        text = "阅读 1.2万\n收藏 3000"
        result = parse_published_metrics(text)
        assert result.values["views"] == 12000
        assert result.values["saves"] == 3000

    def test_k_suffix(self):
        text = "观看 3.5k"
        result = parse_published_metrics(text)
        assert result.values["views"] == 3500

    def test_comma_separated_number(self):
        text = "点赞 1,234"
        result = parse_published_metrics(text)
        assert result.values["likes"] == 1234

    def test_all_null_raises_no_error_but_reports(self):
        """纯函数不 raise；诊断信息里列出 null 字段。"""
        text = "这是一段完全没有指标的文字"
        result = parse_published_metrics(text)
        assert all(v is None for v in result.values.values())
        assert result.strategy_used == "none"
        assert len(result.null_fields) == len(result.values)
        assert result.text_length == len(text)

    def test_partial_fields_some_null(self):
        text = "观看 5000\n点赞 200"
        result = parse_published_metrics(text)
        assert result.values["views"] == 5000
        assert result.values["likes"] == 200
        assert result.values["saves"] is None
        assert "saves" in result.null_fields
        assert "views" not in result.null_fields

    def test_hit_labels_recorded(self):
        text = "阅读 800\n收藏 120"
        result = parse_published_metrics(text)
        # "阅读" 命中 views 别名
        assert result.hit_labels.get("views") == "阅读"
        assert result.hit_labels.get("saves") == "收藏"

    def test_custom_labels(self):
        """自定义标签别名。"""
        custom_labels = {
            "views": ("播放量",),
            "likes": ("点赞数",),
        }
        text = "播放量 5万\n点赞数 3200"
        result = parse_published_metrics(text, labels=custom_labels)
        assert result.values["views"] == 50000
        assert result.values["likes"] == 3200

    def test_exposure_traffic_format(self):
        """创作者中心常见格式：搜索流量 1234 / 推荐流量 5678。"""
        text = "搜索流量 1234\n推荐流量 5678"
        result = parse_published_metrics(text)
        assert result.values["search_views"] == 1234
        assert result.values["recommendation_views"] == 5678

    def test_wan_unit_with_chinese(self):
        """万字中文数字。"""
        text = "观看 2.3万\n涨粉 15"
        result = parse_published_metrics(text)
        assert result.values["views"] == 23000
        assert result.values["follows"] == 15

    def test_empty_text(self):
        result = parse_published_metrics("")
        assert result.strategy_used == "none"
        assert all(v is None for v in result.values.values())

    def test_result_is_metric_parse_result(self):
        result = parse_published_metrics("观看 100")
        assert isinstance(result, MetricParseResult)

    def test_partial_kv_merges_with_label_adjacent(self):
        """KV 只命中部分字段时，应用邻近策略补齐其余字段。"""
        text = "观看：1200\n点赞 328\n收藏 56"
        result = parse_published_metrics(text)
        assert result.values["views"] == 1200
        assert result.values["likes"] == 328
        assert result.values["saves"] == 56
        assert result.strategy_used in ("kv", "label_adjacent", "kv+label_adjacent")

    def test_no_cross_line_number_steal(self):
        """标签后跨行的数字不应被邻近策略吞并。"""
        text = "本周观看占比高于上周\n点赞 12"
        result = parse_published_metrics(text)
        assert result.values["likes"] == 12
        assert result.values["views"] is None