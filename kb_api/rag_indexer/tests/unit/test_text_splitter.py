import pytest

from kb_api.rag_indexer.core.index.text_splitter import split_text


@pytest.mark.parametrize("text,size,overlap,expected", [
    ("", 10, 2, []),
    ("   \n\t", 10, 0, []),
    ("甲乙丙丁。戊己庚辛！壬癸子丑？", 6, 0, ["甲乙丙丁。", "戊己庚辛！", "壬癸子丑？"]),
    ("First sentence. Second sentence! Third sentence?", 20, 5,
     ["First sentence.", "Second sentence!", "Third sentence?"]),
    ("a.b c.d. efg", 6, 1, ["a.b", "c.d.", "efg"]),
    ("aa;bb；cc,dd，ee", 5, 2, ["aa;", "bb；", "cc,", "dd，ee"]),
    ("aa\t bb   cc dd", 6, 2, ["aa", "bb", "cc dd"]),
    ("aa\n\nbb\n\ncc", 6, 2, ["aa", "bb\n\ncc"]),
    ("aa\r\nbb\r\ncc", 5, 1, ["aa", "bb", "cc"]),
    ("ABCDEFGHIJKLMNO", 6, 2, ["ABCDEF", "EFGHIJ", "IJKLMN", "MNO"]),
    ("0123456789", 4, 4, ["0123", "1234", "2345", "3456", "4567", "5678", "6789"]),
    ("abcd\nefghijklm\nxy", 6, 2, ["abcd", "efghij", "ijklm", "xy"]),
    (";;，，！！", 3, 1, [";;", "，，！", "！"]),
    ("  abc  ", 3, 0, ["abc"]),
    ("段落一\n \n段落二。下一句！末尾", 8, 3, ["段落一", "段落二。下一句！", "末尾"]),
    ("a", 1, 1, ["a"]),
    ("a\nb", 1, 0, ["a", "\n", "b"]),
])
def test_split_text_preserves_existing_boundaries_and_overlap(text, size, overlap, expected):
    assert split_text(text, size, overlap) == expected
