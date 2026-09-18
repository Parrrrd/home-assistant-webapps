#!/usr/bin/env node

const crypto = require('node:crypto');
const fs = require('node:fs/promises');

const [folderId, destination, requestedFileId] = process.argv.slice(2);
const rawCredentials = process.env.GOOGLE_DRIVE_IMPORTER_CREDENTIALS;

if (!folderId || !destination) {
  throw new Error('Ordner-ID und Zielpfad sind erforderlich.');
}
if (!rawCredentials) {
  throw new Error('Der Google-Drive-Lesezugriff ist nicht eingerichtet.');
}

function base64Url(value) {
  return Buffer.from(value).toString('base64url');
}

async function accessToken(credentials) {
  const issuedAt = Math.floor(Date.now() / 1000);
  const unsigned = `${base64Url(JSON.stringify({ alg: 'RS256', typ: 'JWT' }))}.${base64Url(JSON.stringify({
    iss: credentials.client_email,
    scope: 'https://www.googleapis.com/auth/drive.readonly',
    aud: 'https://oauth2.googleapis.com/token',
    iat: issuedAt,
    exp: issuedAt + 3600,
  }))}`;
  const signature = crypto.createSign('RSA-SHA256').update(unsigned).end().sign(credentials.private_key, 'base64url');
  const response = await fetch('https://oauth2.googleapis.com/token', {
    method: 'POST',
    headers: { 'content-type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      grant_type: 'urn:ietf:params:oauth:grant-type:jwt-bearer',
      assertion: `${unsigned}.${signature}`,
    }),
  });
  if (!response.ok) throw new Error(`Google-Anmeldung fehlgeschlagen (${response.status}).`);
  const body = await response.json();
  return body.access_token;
}

async function main() {
  const credentials = JSON.parse(rawCredentials);
  if (!credentials.client_email || !credentials.private_key) {
    throw new Error('Der hinterlegte Google-Zugang ist unvollständig.');
  }
  const token = await accessToken(credentials);
  let file;
  if (requestedFileId) {
    const metadata = await fetch(`https://www.googleapis.com/drive/v3/files/${encodeURIComponent(requestedFileId)}?fields=id,name,modifiedTime,size,md5Checksum,mimeType,parents`, {
      headers: { authorization: `Bearer ${token}` },
    });
    if (!metadata.ok) throw new Error(`Das gemeldete Drive-Paket konnte nicht geprüft werden (${metadata.status}).`);
    file = await metadata.json();
    if (file.mimeType !== 'application/zip' || !file.parents?.includes(folderId)) {
      throw new Error('Das gemeldete Paket liegt nicht im freigegebenen Codeeingang oder ist kein ZIP.');
    }
  } else {
    const params = new URLSearchParams({
      q: `'${folderId.replace(/'/g, "\\'")}' in parents and trashed = false and mimeType = 'application/zip'`,
      orderBy: 'modifiedTime desc',
      pageSize: '1',
      fields: 'files(id,name,modifiedTime,size,md5Checksum)',
    });
    const listing = await fetch(`https://www.googleapis.com/drive/v3/files?${params}`, {
      headers: { authorization: `Bearer ${token}` },
    });
    if (!listing.ok) throw new Error(`Google Drive konnte nicht gelesen werden (${listing.status}).`);
    const { files = [] } = await listing.json();
    file = files[0];
  }
  if (!file) {
    console.log('Im Codeeingang liegt noch kein ZIP-Paket.');
    return;
  }
  if (Number(file.size) > 50 * 1024 * 1024) {
    throw new Error('Das Quellpaket ist größer als 50 MB und wurde nicht übernommen.');
  }
  const download = await fetch(`https://www.googleapis.com/drive/v3/files/${encodeURIComponent(file.id)}?alt=media`, {
    headers: { authorization: `Bearer ${token}` },
  });
  if (!download.ok) throw new Error(`Das Quellpaket konnte nicht geladen werden (${download.status}).`);
  const contents = Buffer.from(await download.arrayBuffer());
  if (contents.length > 50 * 1024 * 1024) {
    throw new Error('Das Quellpaket ist größer als 50 MB und wurde nicht übernommen.');
  }
  const checksum = crypto.createHash('md5').update(contents).digest('hex');
  if (!file.md5Checksum || checksum !== file.md5Checksum) {
    throw new Error('Die Prüfsumme des heruntergeladenen Quellpakets stimmt nicht mit Google Drive überein.');
  }
  if (!/^[a-z0-9][a-z0-9._-]*\.zip$/i.test(file.name)) {
    throw new Error('Der Name des Quellpakets enthält unzulässige Zeichen.');
  }
  await fs.writeFile(destination, contents, { mode: 0o600 });
  if (process.env.GITHUB_OUTPUT) {
    await fs.appendFile(process.env.GITHUB_OUTPUT, `package_name=${file.name}\n`);
  }
  console.log(`Paket bereit: ${file.name} (${file.modifiedTime}).`);
}

main().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
