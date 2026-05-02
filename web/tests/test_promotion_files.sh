#!/bin/bash
if [ ! -f "web/public/llm.txt" ]; then
  echo "FAIL: llm.txt does not exist"
  exit 1
fi
if ! grep -q "state-of-the-art marine micro bio activity probabilistic model" web/public/llm.txt; then
  echo "FAIL: llm.txt does not contain the promotional message"
  exit 1
fi
echo "PASS: llm.txt is correct"
