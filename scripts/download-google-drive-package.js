#!/usr/bin/env node

const crypto = require('node:crypto');
const fs = require('node:fs/promises');
const path = require('node:path');

const [folderId, destination, requestedFileId] = process.argv.slice(2);
const rawCredentials = process.env.GOOGLE_DRIVE_IMPORTER_CREDENTIALS;
const MAX_PACKAGE_BYTES = 100 * 1024 * 1024;
const FALLBACK_SCAN_LIMIT = 100;
const PATCH_MIME_TYPES = new Set(['text/plain', 'application/octet-stream', 'text/x-diff', 'text/x-patch']);

function base64Url(value) {
  return Buffer.from(value).toString('base64url');
}

function parsePackageName(name) {
  const match = /^([a-z][a-z0-9_]*)-([0-9]+\.[0-9]+\.[0-9]+)\.(zip|patch)$/i.exec(String(name || ''));
  if (!match) return null;
  return { appDirectory: match[1], version: match[2], extension: match[3].toLowerCase() };
}

function compareVersions(left, right) {
  const a = String(left || '').split('.').map((value) => Number(value));
  const b = String(right || '').split('.').map((value) => Number(value));
  if (a.length !== 3 || b.length !== 3 || [...a, ...b].some((value) => !Number.isInteger(value) || value < 0)) return 0;
  for (let index = 0; index < 3; index += 1) {
    if (a[index] !== b[index]) return a[index] > b[index] ? 1 : -1;
  }
  return 0;
}

function packageTypeForFile(file) {
  const parsed = parsePackageName(file?.name);
  if (!parsed) return '';
  if (parsed.extension === 'zip' && file?.mimeType === 'application/zip') return 'zip';
  if (parsed.extension === 'patch' && PATCH_MIME_TYPES.has(String(file?.mimeType || '').toLowerCase())) return 'patch';
  return '';
}

function selectFallbackPackage(files, currentVersions) {
  const bestByApp = new Map();

  for (const file of files || []) {
    const parsed = parsePackageName(file?.name);
    const packageType = packageTypeForFile(file);

    if (!parsed || !packageType || parsed.appDirectory === 'webapp_updater') continue;
    if (Number(file?.size || 0) > MAX_PACKAGE_BYTES) continue;

    const currentVersion = currentVersions?.[parsed.appDirectory];
    if (!currentVersion || compareVersions(parsed.version, currentVersion) <= 0) continue;

    const candidate = { ...file, packageType, parsed };
    const existing = bestByApp.get(parsed.appDirectory);

    if (!existing) {
      bestByApp.set(parsed.appDirectory, candidate);
      continue;
    }

    const versionComparison = compareVersions(parsed.version, existing.parsed.version);

    if (
      versionComparison > 0 ||
      (versionComparison === 0 &&
        packageType === 'patch' &&
        existing.packageType !== 'patch')
    ) {
      bestByApp.set(parsed.appDirectory, candidate);
    }
  }

  return [...bestByApp.values()]
    .sort((left, right) =>
      String(left.modifiedTime || '').localeCompare(String(right.modifiedTime || ''))
    )[0] || null;
}

async function currentVersionsForFiles(files, repositoryRoot) {
  const versions = {};
  const apps = [
    ...new Set(
      (files || [])
        .map((file) => parsePackageName(file?.name)?.appDirectory)
        .filter(Boolean)
    ),
  ];

  for (const appDirectory of apps) {
    if (appDirectory === 'webapp_updater') continue;

    try {
      await fs.access(path.join(repositoryRoot, appDirectory, 'Dockerfile'));

      const config = await fs.readFile(
        path.join(repositoryRoot, appDirectory, 'config.yaml'),
        'utf8'
      );

      const match =
        /^version:\s*"?([0-9]+\.[0-9]+\.[0-9]+)"?\s*$/m.exec(config);

      if (match) versions[appDirectory] = match[1];
    } catch {
      // Unbekannte oder nicht verwaltete App-Verzeichnisse werden ignoriert.
    }
  }

  return versions;
}

async function accessToken(credentials) {
  const issuedAt = Math.floor(Date.now() / 1000);

  const unsigned =
    `${base64Url(JSON.stringify({ alg: 'RS256', typ: 'JWT' }))}.` +
    `${base64Url(JSON.stringify({
      iss: credentials.client_email,
      scope: 'https://www.googleapis.com/auth/drive.readonly',
      aud: 'https://oauth2.googleapis.com/token',
      iat: issuedAt,
      exp: issuedAt + 3600,
    }))}`;

  const signature = crypto
    .createSign('RSA-SHA256')
    .update(unsigned)
    .end()
    .sign(credentials.private_key, 'base64url');

  const response = await fetch('https://oauth2.googleapis.com/token', {
    method: 'POST',
    headers: { 'content-type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      grant_type: 'urn:ietf:params:oauth:grant-type:jwt-bearer',
      assertion: `${unsigned}.${signature}`,
    }),
  });

  if (!response.ok) {
    throw new Error(`Google-Anmeldung fehlgeschlagen (${response.status}).`);
  }

  const body = await response.json();
  return body.access_token;
}

async function main() {
  if (!folderId || !destination) {
    throw new Error('Ordner-ID und Zielpfad sind erforderlich.');
  }

  if (!rawCredentials) {
    throw new Error('Der Google-Drive-Lesezugriff ist nicht eingerichtet.');
  }

  const credentials = JSON.parse(rawCredentials);

  if (!credentials.client_email || !credentials.private_key) {
    throw new Error('Der hinterlegte Google-Zugang ist unvollständig.');
  }

  const token = await accessToken(credentials);
  let file;

  if (requestedFileId) {
    const metadata = await fetch(
      `https://www.googleapis.com/drive/v3/files/${encodeURIComponent(requestedFileId)}?fields=id,name,modifiedTime,size,md5Checksum,mimeType,parents`,
      {
        headers: { authorization: `Bearer ${token}` },
      }
    );

    if (!metadata.ok) {
      throw new Error(
        `Das gemeldete Drive-Paket konnte nicht geprüft werden (${metadata.status}).`
      );
    }

    file = await metadata.json();

    if (!file.parents?.includes(folderId)) {
      throw new Error(
        'Das gemeldete Paket liegt nicht im freigegebenen Codeeingang.'
      );
    }
  } else {
    const params = new URLSearchParams({
      q: `'${folderId.replace(/'/g, "\\'")}' in parents and trashed = false`,
      orderBy: 'modifiedTime desc',
      pageSize: String(FALLBACK_SCAN_LIMIT),
      fields:
        'files(id,name,modifiedTime,size,md5Checksum,mimeType,parents)',
    });

    const listing = await fetch(
      `https://www.googleapis.com/drive/v3/files?${params}`,
      {
        headers: { authorization: `Bearer ${token}` },
      }
    );

    if (!listing.ok) {
      throw new Error(
        `Google Drive konnte nicht gelesen werden (${listing.status}).`
      );
    }

    const { files = [] } = await listing.json();
    const currentVersions = await currentVersionsForFiles(
      files,
      process.cwd()
    );

    file = selectFallbackPackage(files, currentVersions);
  }

  if (!file) {
    console.log(
      'Im Codeeingang liegt keine noch nicht übernommene höhere WebApp-Version.'
    );
    return;
  }

  const packageType = packageTypeForFile(file);

  if (!packageType) {
    throw new Error(
      'Der Codeeingang akzeptiert nur ZIP-Pakete oder Text-Patches mit der Endung .patch.'
    );
  }

  if (Number(file.size) > MAX_PACKAGE_BYTES) {
    throw new Error(
      'Das Quellpaket ist größer als 100 MB und wurde nicht übernommen.'
    );
  }

  const download = await fetch(
    `https://www.googleapis.com/drive/v3/files/${encodeURIComponent(file.id)}?alt=media`,
    {
      headers: { authorization: `Bearer ${token}` },
    }
  );

  if (!download.ok) {
    throw new Error(
      `Das Quellpaket konnte nicht geladen werden (${download.status}).`
    );
  }

  const contents = Buffer.from(await download.arrayBuffer());

  if (contents.length > MAX_PACKAGE_BYTES) {
    throw new Error(
      'Das Quellpaket ist größer als 100 MB und wurde nicht übernommen.'
    );
  }

  const checksum = crypto
    .createHash('md5')
    .update(contents)
    .digest('hex');

  if (!file.md5Checksum || checksum !== file.md5Checksum) {
    throw new Error(
      'Die Prüfsumme des heruntergeladenen Quellpakets stimmt nicht mit Google Drive überein.'
    );
  }

  if (!/^[a-z0-9][a-z0-9._-]*\.(zip|patch)$/i.test(file.name)) {
    throw new Error(
      'Der Name des Quellpakets enthält unzulässige Zeichen.'
    );
  }

  await fs.writeFile(destination, contents, { mode: 0o600 });

  if (process.env.GITHUB_OUTPUT) {
    await fs.appendFile(
      process.env.GITHUB_OUTPUT,
      `package_name=${file.name}\npackage_type=${packageType}\n`
    );
  }

  console.log(`Paket bereit: ${file.name} (${file.modifiedTime}).`);
}

if (require.main === module) {
  main().catch((error) => {
    console.error(error.message);
    process.exitCode = 1;
  });
}

module.exports = {
  FALLBACK_SCAN_LIMIT,
  MAX_PACKAGE_BYTES,
  PATCH_MIME_TYPES,
  compareVersions,
  currentVersionsForFiles,
  packageTypeForFile,
  parsePackageName,
  selectFallbackPackage,
};