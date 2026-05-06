#!/bin/bash
cd "$(dirname "$0")" || exit 1
echo "Starting EAS build..." > build_and_submit.log
eas build --platform ios --profile production --local --non-interactive >> build_and_submit.log 2>&1
if [ $? -eq 0 ]; then
  echo "Build successful. Finding IPA file..." >> build_and_submit.log
  IPA_FILE=$(ls -t build-*.ipa 2>/dev/null | head -n 1)
  if [ -n "$IPA_FILE" ]; then
    echo "Submitting $IPA_FILE to TestFlight..." >> build_and_submit.log
    eas submit --platform ios --profile production --path "$IPA_FILE" --non-interactive >> build_and_submit.log 2>&1
    if [ $? -eq 0 ]; then
      echo "Submission successful." >> build_and_submit.log
    else
      echo "Submission failed." >> build_and_submit.log
    fi
  else
    echo "IPA file not found." >> build_and_submit.log
  fi
else
  echo "EAS build failed." >> build_and_submit.log
fi
