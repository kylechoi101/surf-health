const fs = require('fs');
const path = require('path');

const appJsonPath = path.join(__dirname, '../app.json');
const appJson = require(appJsonPath);

const currentVersion = appJson.expo.version;
const parts = currentVersion.split('.');
const patch = parseInt(parts[2], 10) + 1;
const newVersion = `${parts[0]}.${parts[1]}.${patch}`;

appJson.expo.version = newVersion;
fs.writeFileSync(appJsonPath, JSON.stringify(appJson, null, 2) + '\n');
console.log(`Bumped expo.version from ${currentVersion} to ${newVersion} in app.json`);
