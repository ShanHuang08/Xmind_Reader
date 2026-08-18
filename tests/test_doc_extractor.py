from __future__ import annotations

import unittest

from doc_reader.doc_extractor import (
    _extract_vendor_master_checklist,
    extract_vendor_detail,
)


class DocExtractorTests(unittest.TestCase):
    def test_checklist_preserves_selected_confluence_task_values(self) -> None:
        parsed = {
            "tables": [
                [
                    ["Name", "Description", "Remark", "enable"],
                    ["Game Type", "有哪些類型遊戲", "", "checked"],
                ]
            ],
            "tables_detailed": [
                [
                    [{"text": "Name"}, {"text": "Description"}, {"text": "Remark"}, {"text": "enable"}],
                    [
                        {"text": "Game Type"},
                        {"text": "有哪些類型遊戲"},
                        {"text": ""},
                        {
                            "text": "Slot Game\nLive Game\nVideo Bingo",
                            "tasks": [
                                {"text": "Slot Game", "checked": True},
                                {"text": "Live Game", "checked": False},
                                {"text": "Video Bingo", "checked": True},
                            ],
                        },
                    ],
                ]
            ],
        }

        checklist = _extract_vendor_master_checklist(parsed)

        self.assertEqual(checklist[0]["available_values"], ["Slot Game", "Live Game", "Video Bingo"])
        self.assertEqual(checklist[0]["selected_values"], ["Slot Game", "Video Bingo"])

    def test_h2_query_operations_become_variants_with_xml_responses(self) -> None:
        request_table = [
            ["Parameter", "Type", "Require", "Description"],
            ["userId", "String", "Y", "Player"],
            ["hash", "String", "Y", "Signature"],
        ]
        response_table = [
            ["Parameter", "Type", "Require", "Description"],
            ["balance", "Integer", "Y", "Balance"],
        ]
        xml = """<EXTSYSTEM><REQUEST><USERID>u1</USERID></REQUEST>
        <RESPONSE><RESULT>ERROR</RESULT><CODE>610</CODE></RESPONSE></EXTSYSTEM>"""
        parsed = {
            "source_file": "vendor.doc",
            "plain_text": "",
            "paragraphs": [
                {"style": "h2", "text": "2.1 /api/v1/wallet.do (Bet)"},
                {"style": "p", "text": "request example:"},
                {"style": "pre", "text": "https://example.com/api/v1/wallet.do?\n&userId=u1\n&hash=abc"},
                {"style": "pre", "text": xml},
                {"style": "h2", "text": "2.2 /api/v1/wallet.do (Win)"},
                {"style": "p", "text": "request example:"},
                {"style": "pre", "text": "https://example.com/api/v1/wallet.do?\n&userId=u1\n&hash=def"},
                {"style": "pre", "text": xml},
            ],
            "tables": [request_table, response_table, request_table, response_table],
        }

        detail = extract_vendor_detail(parsed, "vendor")

        self.assertEqual(len(detail["endpoints"]), 1)
        endpoint = detail["endpoints"][0]
        self.assertEqual(endpoint["endpoint"], "/api/v1/wallet.do")
        self.assertEqual(len(endpoint["operation_variants"]), 2)
        self.assertEqual(
            [variant["operation"] for variant in endpoint["operation_variants"]],
            ["Bet", "Win"],
        )
        self.assertEqual(
            endpoint["operation_variants"][0]["request_example"],
            {"userId": "u1", "hash": "abc"},
        )
        self.assertEqual(
            endpoint["operation_variants"][0]["error_response_example"],
            {"result": "ERROR", "code": "610"},
        )


if __name__ == "__main__":
    unittest.main()
