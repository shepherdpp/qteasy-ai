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

import unittest

from qteasy_ai.slot_graph import commit_freq, commit_query, commit_shares, commit_weight_text


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


if __name__ == "__main__":
    unittest.main()
