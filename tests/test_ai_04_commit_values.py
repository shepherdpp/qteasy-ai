# coding=utf-8
# ======================================
# File: test_ai_04_commit_values.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-09
# Desc:
# 参数提交门闸：代码、频率、权重三种值。
# 不启动 Planner。
# ======================================

import inspect
import unittest

from qteasy_ai.app import build_default_registry
from qteasy_ai.skills.data_history import build_data_history_skill
from qteasy_ai.skills.data_reference import build_data_reference_skill
from qteasy_ai.skills.data_static import build_data_static_skill
from qteasy_ai.slot_graph import (
    _card_prompt,
    _fill_prompt,
    _options_for,
    _pending_row,
    _reject_reason,
    _spec_extras,
    accept_slot_value,
    code_spec,
    commit_freq,
    commit_query,
    commit_shares,
    commit_weight_text,
    dtype_spec,
    dtype_subset_ids,
    weights_spec,
)


class TestAi04CommitValues(unittest.TestCase):
    """一次提交只放出能调用的值。"""

    def test_symbols_keep_order_and_refuse_partial(self) -> None:
        """带后缀按出现顺序。两只裸代码都要落上。两义代码整组未完成。"""

        print("\n[TestAi04CommitValues] 代码提交")
        ordered = commit_shares("000858.SZ 和 600519.SH")
        bare = commit_shares("600519 和 000858")
        ambiguous = commit_shares("000001")
        named = commit_shares("000001 与 000300，并说明 000300 是指数")
        index_name = commit_shares("沪深300")
        company = commit_query("茅台和五粮液放一起")
        print(" ordered:", ordered)
        print(" bare:", bare)
        print(" ambiguous:", ambiguous)
        print(" named:", named)
        print(" index:", index_name)
        print(" company:", company)
        self.assertEqual(ordered["value"], "000858.SZ,600519.SH")
        self.assertEqual(bare["value"], "600519.SH,000858.SZ")
        self.assertNotEqual(bare["value"], "600519.SH")
        self.assertEqual(ambiguous["status"], "unresolved")
        self.assertEqual(named["status"], "unresolved")
        self.assertEqual(index_name["value"], "000300.SH")
        self.assertNotIn("shares", company["values"])
        self.assertNotIn("600519", str(company))

    def test_frequency_must_bind_when_named(self) -> None:
        """周线收成 w。点了频率却认不出时，不能靠缺省日线通过。"""

        print("\n[TestAi04CommitValues] 频率提交")
        weekly = commit_query("取数周线，做一条等权组合")
        named = commit_freq("按频率看看")
        print(" weekly:", weekly["values"].get("freq"), weekly["unresolved"])
        print(" named:", named)
        self.assertEqual(weekly["values"].get("freq"), "w")
        self.assertEqual(named["status"], "unresolved")
        self.assertNotEqual(named["value"], "d")

    def test_weights_become_numbers_or_equal(self) -> None:
        """比例收成数字。等权不带 weights。原文不能通过。"""

        print("\n[TestAi04CommitValues] 权重提交")
        samples = {
            "6:4": [6.0, 4.0],
            "6比4": [6.0, 4.0],
            "60%,40%": [60.0, 40.0],
            "1:1": [1.0, 1.0],
        }
        for text, expect in samples.items():
            parsed = commit_weight_text(text)
            print(" ratio:", text, parsed)
            self.assertEqual(parsed["status"], "value")
            self.assertEqual(parsed["values"].get("mode"), "weighted")
            self.assertEqual(parsed["values"].get("weights"), expect)
            self.assertNotIn(text, parsed["values"].values())
        for text in ("等权", "一样重要"):
            parsed = commit_weight_text(text)
            print(" equal:", text, parsed)
            self.assertEqual(parsed["values"], {"mode": "equal"})
            self.assertNotIn("weights", parsed["values"])
            self.assertNotIn(text, parsed["values"].values())
        raw = commit_weight_text("请给权重")
        print(" raw:", raw)
        self.assertEqual(raw["status"], "unresolved")
        self.assertEqual(raw["values"], {})

    def test_code_weight_text_is_refused_without_858(self) -> None:
        """代码映射和夹着证券代码的数字整段拒绝，不收出 858。"""

        print("\n[TestAi04CommitValues] 代码权重整段拒绝")
        mapped = "600519.SH=0.5,000858.SZ=0.5"
        glued = "0.5,000858"
        kept = commit_weight_text("600519 和 000858 按权重 6:4")
        word = commit_weight_text("equal")
        negated = commit_weight_text("unequal")
        slot = weights_spec()
        mapped_parsed = commit_weight_text(mapped)
        glued_parsed = commit_weight_text(glued)
        mapped_reason = _reject_reason(slot, mapped)
        glued_reason = _reject_reason(slot, glued)
        prompt = _fill_prompt(None, [{"name": "weights", **slot}], "各占一半")
        head = prompt.split("slot:")[0]
        print(" mapped:", mapped_parsed, mapped_reason)
        print(" glued:", glued_parsed, glued_reason)
        print(" kept:", kept)
        print(" equal word:", word, "unequal:", negated)
        print(" prompt head has example:", "[0.5, 0.5]" in head)
        self.assertNotEqual(mapped_parsed["status"], "value")
        self.assertNotIn(858.0, mapped_parsed["values"].get("weights") or [])
        self.assertNotEqual(glued_parsed["status"], "value")
        self.assertNotIn(858.0, glued_parsed["values"].get("weights") or [])
        self.assertIn("[0.5, 0.5]", mapped_reason)
        self.assertIn("[0.5, 0.5]", glued_reason)
        self.assertEqual(kept["values"].get("weights"), [6.0, 4.0])
        self.assertEqual(word["values"], {"mode": "equal"})
        self.assertNotIn("weights", word["values"])
        self.assertNotEqual(negated["values"].get("mode"), "equal")
        self.assertEqual(slot.get("example"), "[0.5, 0.5]")
        self.assertIn("[0.5, 0.5]", prompt)
        self.assertIn(str(slot.get("constraint") or ""), prompt)
        self.assertNotIn("[0.5, 0.5]", head)
        self.assertNotIn("[0.5, 0.5]", inspect.getsource(_fill_prompt))
        self.assertNotIn("[0.5, 0.5]", inspect.getsource(_card_prompt))

    def test_dtype_examples_are_not_the_full_catalog(self) -> None:
        """K 线短名单是例子。未声明子集时 pe 仍收下。代码槽带上例子。"""

        print("\n[TestAi04CommitValues] 数据类型例子与代码槽")
        kline = ("open", "high", "low", "close", "volume")
        plain = dtype_spec(required=True)
        shown = dtype_spec(required=True, examples=kline)
        history = build_data_history_skill()[0].inputs_schema["htype_names"]
        static_names = build_data_static_skill()[0].inputs_schema["names"]
        reference_names = build_data_reference_skill()[0].inputs_schema["names"]
        slot = {"name": "htype_names", **shown}
        subset = {**slot, "dtype_subset": "kline"}
        close = accept_slot_value(slot, "close", "close")
        pe = accept_slot_value(slot, "pe", "pe")
        company = accept_slot_value(slot, "贵州茅台", "贵州茅台")
        blocked = accept_slot_value(subset, "pe", "pe")
        company_reason = _reject_reason(slot, "贵州茅台")
        subset_reason = _reject_reason(subset, "pe")
        extra = _spec_extras(shown)
        card = _card_prompt("看行情", [], {}, {"htype_names": "贵州茅台"}, [slot])
        contract = [line for line in card.splitlines() if line.startswith("contract=")]
        fill = _fill_prompt(None, [slot], "看收盘")
        options = [item.get("id") for item in _options_for("htype_names", slot)]
        code = code_spec(required=True)
        element = code_spec(required=True, element="holding", min_count=2)
        code_prompt = _fill_prompt(None, [{"name": "shares", **code}], "两只股票")
        row = _pending_row({"name": "htype_names", "type": "string"}, "", "看")
        registry = build_default_registry()
        declared = []
        for meta in registry.list_skills():
            for spec in (meta.inputs_schema or {}).values():
                if isinstance(spec, dict) and spec.get("dtype_subset"):
                    declared.append((meta.name, spec.get("dtype_subset")))
        print(" plain keys:", sorted(plain))
        print(" history examples:", history.get("dtype_examples"), "subset:", history.get("dtype_subset"))
        print(" close:", close, "pe:", pe, "company:", company, "blocked:", blocked)
        print(" company reason:", company_reason)
        print(" subset reason:", subset_reason)
        print(" contract:", contract)
        print(" options:", options)
        print(" declared subsets:", declared)
        print(" code example:", code.get("example"))
        print(" label:", row.get("label"), "hint:", row.get("hint"))
        self.assertNotIn("dtype_examples", plain)
        self.assertNotIn("example", plain)
        self.assertEqual(dtype_subset_ids("kline"), kline)
        self.assertEqual(dtype_subset_ids("valuation"), ("pe", "pb"))
        self.assertIsNone(dtype_subset_ids(""))
        self.assertEqual(list(history.get("dtype_examples") or []), list(kline))
        self.assertNotIn("dtype_subset", history)
        self.assertNotIn("enum", history)
        self.assertNotIn("dtype_examples", static_names)
        self.assertNotIn("dtype_examples", reference_names)
        self.assertEqual(extra.get("dtype_examples"), list(kline))
        self.assertNotIn("enum", extra)
        self.assertEqual(close, "close")
        self.assertEqual(pe, "pe")
        self.assertIsNone(company)
        self.assertIsNone(blocked)
        self.assertIn("data type", company_reason.lower())
        self.assertIn("close", company_reason)
        self.assertIn("kline", subset_reason)
        self.assertIn("not the full catalog", card)
        self.assertIn("not the full catalog", fill)
        self.assertTrue(contract)
        self.assertTrue(all(line == "contract=" for line in contract))
        self.assertNotIn("enum=", card)
        self.assertEqual(options, list(kline))
        self.assertEqual(declared, [])
        self.assertEqual(code.get("example"), "600519.SH,000858.SZ")
        self.assertEqual(element.get("example"), "600519.SH,000858.SZ")
        self.assertIn("company names", str(code.get("constraint") or "").lower())
        self.assertIn("code=name", str(element.get("constraint") or ""))
        self.assertIn("600519.SH,000858.SZ", code_prompt)
        self.assertNotEqual(row.get("label"), "History columns")
        self.assertNotIn("history column names", str(row.get("hint") or "").lower())
