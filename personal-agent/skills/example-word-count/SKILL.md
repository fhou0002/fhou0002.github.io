---
name: example-word-count
description: Counts words, characters and lines in a piece of text. Use when the user asks to count words/characters/lines in some text.
---

# Word Count

To count words/characters/lines in a piece of text:

1. Write the text to a temporary file if it's long, or pass it directly as an argument.
2. Run `scripts/count_words.py "<text>"` via `run_skill_script`.
3. Report the word count, character count and line count back to the user.
