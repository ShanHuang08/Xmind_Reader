from __future__ import annotations

from pathlib import Path
import unittest

from doc_reader.doc_parser import _parse_html_document


class DocParserCheckboxTests(unittest.TestCase):
    def test_inline_tasks_keep_per_item_checked_state(self) -> None:
        parsed = _parse_html_document(
            Path("vendor.html"),
            """
            <html><body><table>
              <tr><th>Name</th><th>enable</th></tr>
              <tr><td>Game Type</td><td>
                <ul class="inline-task-list">
                  <li class="checked"><span>Slot Game</span></li>
                  <li><span>Live Game</span></li>
                  <li class="checked"><span>Video Bingo</span></li>
                </ul>
              </td></tr>
            </table></body></html>
            """,
        )

        cell = parsed["tables_detailed"][0][1][1]
        self.assertEqual(cell["checkbox"], "checked")
        self.assertEqual(
            cell["tasks"],
            [
                {"text": "Slot Game", "checked": True},
                {"text": "Live Game", "checked": False},
                {"text": "Video Bingo", "checked": True},
            ],
        )


if __name__ == "__main__":
    unittest.main()
