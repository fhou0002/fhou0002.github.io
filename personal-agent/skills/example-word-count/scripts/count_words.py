#!/usr/bin/env python3
import sys

text = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read()
print(f"words={len(text.split())} chars={len(text)} lines={len(text.splitlines()) or 1}")
