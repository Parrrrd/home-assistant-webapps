const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(
  path.join(
    __dirname,
    '..',
    'automation',
    'google-drive-dispatch',
    'Code.gs'
  ),
  'utf8'
);

const sandbox = {};
vm.runInNewContext(
  `${source}\nthis.__dispatchTest = { DRIVE_IMPORT_FOLDER_ID, PATCH_MIME_TYPES, isSupportedPackage };`,
  sandbox,
  { filename: 'automation/google-drive-dispatch/Code.gs' }
);

const { DRIVE_IMPORT_FOLDER_ID, PATCH_MIME_TYPES, isSupportedPackage } =
  sandbox.__dispatchTest;

function driveFile(name, mimeType) {
  return {
    getName: () => name,
    getMimeType: () => mimeType,
  };
}

test('dispatch reads the current Bootstrap folder', () => {
  assert.equal(
    DRIVE_IMPORT_FOLDER_ID,
    '1jsOMOVoX_QBfSVvD5ikepLzLoOPH8E_U'
  );
});

test('dispatch accepts all supported patch MIME types', () => {
  const expectedMimeTypes = [
    'text/plain',
    'application/octet-stream',
    'text/x-diff',
    'text/x-patch',
  ];

  assert.deepEqual(Array.from(PATCH_MIME_TYPES), expectedMimeTypes);
  for (const mimeType of expectedMimeTypes) {
    assert.equal(
      isSupportedPackage(
        driveFile('kleinanzeigen_manager-1.6.52.patch', mimeType)
      ),
      true
    );
  }
});

test('dispatch keeps ZIP support and rejects unsupported patch files', () => {
  assert.equal(
    isSupportedPackage(
      driveFile('kleinanzeigen_manager-1.6.52.zip', 'application/zip')
    ),
    true
  );
  assert.equal(
    isSupportedPackage(
      driveFile('kleinanzeigen_manager-1.6.52.patch', 'application/pdf')
    ),
    false
  );
  assert.equal(
    isSupportedPackage(
      driveFile('kleinanzeigen_manager-1.6.52.txt', 'text/x-diff')
    ),
    false
  );
});
