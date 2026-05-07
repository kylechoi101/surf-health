#!/bin/bash

# Navigate to the mobile directory
cd "$(dirname "$0")" || exit 1

echo "Starting EAS cloud build for Android..."

# We use cloud build because local Android builds require Java and Android SDK to be installed.
eas build --platform android --profile production --non-interactive

# Wait for the user to confirm they want to submit.
# Note: Google requires the VERY FIRST .aab to be uploaded manually through the Play Console UI.
echo ""
echo "========================================================="
echo "Build complete! If this is your first time releasing the"
echo "app, you MUST upload the .aab file manually in the"
echo "Google Play Console before using EAS Submit."
echo "========================================================="
echo ""
read -p "Do you want to submit this build to the Google Play Store now? (y/N) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    # Check if the service account key exists where eas.json expects it
    if [ ! -f "../google-services.json" ]; then
        echo "Error: google-services.json not found in the root directory!"
        echo "Please download your Service Account JSON key from Google Cloud,"
        echo "save it as 'google-services.json' in the surf_health folder, and try again."
        exit 1
    fi

    echo "Submitting to Google Play Store..."
    # The --latest flag tells EAS to submit the most recently completed build for this project.
    eas submit --platform android --profile production --latest
else
    echo "Submission cancelled."
fi
