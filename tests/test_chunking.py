import pytest
import sys
import os

# Add parent directory to path so we can import from main.py
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main

def test_paragraph_merging_latin(monkeypatch):
    """
    Test that short Latin paragraphs are merged into a single chunk
    and separated by \\n\\n to preserve TTS pauses.
    """
    # Mock limits so they don't break on the first sentence
    monkeypatch.setattr(main, "DEFAULT_CHUNK_SIZES", [1000])
    monkeypatch.setattr(main, "DEFAULT_MAX_SENTENCES_PER_CHUNK", [50])
    
    text = "Line 1.\n\nLine 2."
    chunks = main.split_text_into_chunks(text, language="en")
    
    assert len(chunks) == 1
    # Check that paragraphs merged with \n\n
    assert chunks[0] == "Line 1.\n\nLine 2."


def test_paragraph_merging_cjk(monkeypatch):
    """
    Test that short CJK paragraphs are merged into a single chunk
    and separated by \\n\\n to preserve TTS pauses.
    """
    # Mock CJK limits so they don't break on the first sentence
    monkeypatch.setattr(main, "CJK_CHUNK_SIZES", [1000])
    monkeypatch.setattr(main, "CJK_MAX_SENTENCES_PER_CHUNK", [50])
    
    text = "你好\n\n世界"
    chunks = main.split_text_into_chunks(text, language="zh")
    
    assert len(chunks) == 1
    # Check that paragraphs merged with \n\n instead of joining directly
    assert chunks[0] == "你好\n\n世界"


def test_paragraph_merging_state_persists(monkeypatch):
    """
    Test that sentence_count state correctly persists across paragraph merges
    and respects the limits.
    """
    monkeypatch.setattr(main, "DEFAULT_CHUNK_SIZES", [1000])
    # Limit max sentences to 2
    monkeypatch.setattr(main, "DEFAULT_MAX_SENTENCES_PER_CHUNK", [2])
    
    text = "Sent 1.\n\nSent 2.\n\nSent 3."
    chunks = main.split_text_into_chunks(text, language="en")
    
    # Needs 2 chunks because max sentences = 2
    assert len(chunks) == 2
    assert chunks[0] == "Sent 1.\n\nSent 2."
    assert chunks[1] == "Sent 3."
