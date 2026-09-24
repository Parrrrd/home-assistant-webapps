const test = require('node:test');
const assert = require('node:assert/strict');

const {
  FALLBACK_SCAN_LIMIT,
  MAX_PACKAGE_BYTES,
  PATCH_MIME_TYPES,
  compareVersions,
  packageTypeForFile,
  parsePackageName,
  selectFallbackPackage,
} = require('./download-google-drive-package');

test(
  'package limit is 100 MB and fallback scans up to 100 files',
  () => {
    assert.equal(
      MAX_PACKAGE_BYTES,
      100 * 1024 * 1024
    );

    assert.equal(
      FALLBACK_SCAN_LIMIT,
      100
    );
  }
);

test(
  'patch MIME types include text/x-diff and text/x-patch',
  () => {
    assert.equal(
      PATCH_MIME_TYPES.has(
        'text/x-diff'
      ),
      true
    );

    assert.equal(
      PATCH_MIME_TYPES.has(
        'text/x-patch'
      ),
      true
    );

    assert.equal(
      packageTypeForFile({
        name:
          'einkaufsliste-0.3.74.patch',
        mimeType:
          'text/x-diff',
      }),
      'patch'
    );
  }
);

test(
  'package names and semantic versions are parsed and compared correctly',
  () => {
    assert.deepEqual(
      parsePackageName(
        'einkaufsliste-0.3.74.patch'
      ),
      {
        appDirectory:
          'einkaufsliste',
        version: '0.3.74',
        extension: 'patch',
      }
    );

    assert.equal(
      compareVersions(
        '0.3.74',
        '0.3.72'
      ),
      1
    );

    assert.equal(
      compareVersions(
        '0.3.72',
        '0.3.74'
      ),
      -1
    );

    assert.equal(
      compareVersions(
        '0.3.74',
        '0.3.74'
      ),
      0
    );

    assert.equal(
      compareVersions(
        '1.10.0',
        '1.9.9'
      ),
      1
    );
  }
);

test(
  'fallback skips current, old and oversized packages and selects an open higher version',
  () => {
    const files = [
      {
        id: 'too-big',
        name:
          'einkaufsliste-0.3.80.zip',
        mimeType:
          'application/zip',
        size: String(
          101 *
            1024 *
            1024
        ),
        modifiedTime:
          '2026-09-24T16:00:00Z',
      },
      {
        id: 'old-version',
        name:
          'einkaufsliste-0.3.72.patch',
        mimeType:
          'text/x-diff',
        size: '1000',
        modifiedTime:
          '2026-09-24T15:59:00Z',
      },
      {
        id: 'open-version',
        name:
          'einkaufsliste-0.3.74.patch',
        mimeType:
          'text/x-diff',
        size: '66982',
        modifiedTime:
          '2026-09-24T15:58:00Z',
      },
      {
        id:
          'other-app-current',
        name:
          'vinted_manager-0.13.145.zip',
        mimeType:
          'application/zip',
        size: '382403',
        modifiedTime:
          '2026-09-24T16:10:00Z',
      },
    ];

    const selected =
      selectFallbackPackage(
        files,
        {
          einkaufsliste:
            '0.3.72',
          vinted_manager:
            '0.13.145',
        }
      );

    assert.ok(selected);

    assert.equal(
      selected.id,
      'open-version'
    );

    assert.equal(
      selected.parsed
        .appDirectory,
      'einkaufsliste'
    );

    assert.equal(
      selected.parsed.version,
      '0.3.74'
    );

    assert.equal(
      selected.bootstrap,
      false
    );
  }
);

test(
  'fallback keeps only the highest open version per app and prefers patch for equal versions',
  () => {
    const files = [
      {
        id: 'einkauf-zip',
        name:
          'einkaufsliste-0.3.74.zip',
        mimeType:
          'application/zip',
        size: String(
          59 *
            1024 *
            1024
        ),
        modifiedTime:
          '2026-09-24T14:00:00Z',
      },
      {
        id:
          'einkauf-patch',
        name:
          'einkaufsliste-0.3.74.patch',
        mimeType:
          'text/x-diff',
        size: '66982',
        modifiedTime:
          '2026-09-24T13:59:00Z',
      },
      {
        id:
          'einkauf-older',
        name:
          'einkaufsliste-0.3.73.patch',
        mimeType:
          'text/x-diff',
        size: '65000',
        modifiedTime:
          '2026-09-24T13:58:00Z',
      },
      {
        id: 'center-parcs',
        name:
          'center_parcs_preisueberwachung-0.3.28.zip',
        mimeType:
          'application/zip',
        size: '95000',
        modifiedTime:
          '2026-09-24T14:30:00Z',
      },
    ];

    const selected =
      selectFallbackPackage(
        files,
        {
          einkaufsliste:
            '0.3.72',
          center_parcs_preisueberwachung:
            '0.3.27',
        }
      );

    assert.ok(selected);

    assert.equal(
      selected.id,
      'einkauf-patch'
    );

    assert.equal(
      selected.packageType,
      'patch'
    );

    assert.equal(
      selected.bootstrap,
      false
    );
  }
);

test(
  'fallback accepts exactly a 0.1.0 ZIP as bootstrap for a new app',
  () => {
    const selected =
      selectFallbackPackage(
        [
          {
            id: 'new-app',
            name:
              'neue_webapp-0.1.0.zip',
            mimeType:
              'application/zip',
            size: '50000',
            modifiedTime:
              '2026-09-24T18:00:00Z',
          },
        ],
        {}
      );

    assert.ok(selected);

    assert.equal(
      selected.id,
      'new-app'
    );

    assert.equal(
      selected.parsed
        .appDirectory,
      'neue_webapp'
    );

    assert.equal(
      selected.parsed.version,
      '0.1.0'
    );

    assert.equal(
      selected.packageType,
      'zip'
    );

    assert.equal(
      selected.bootstrap,
      true
    );
  }
);

test(
  'fallback rejects a patch for an unknown app',
  () => {
    const selected =
      selectFallbackPackage(
        [
          {
            id: 'new-patch',
            name:
              'neue_webapp-0.1.0.patch',
            mimeType:
              'text/x-diff',
            size: '1000',
            modifiedTime:
              '2026-09-24T18:01:00Z',
          },
        ],
        {}
      );

    assert.equal(
      selected,
      null
    );
  }
);

test(
  'fallback rejects a later initial version for an unknown app',
  () => {
    const selected =
      selectFallbackPackage(
        [
          {
            id:
              'new-later-version',
            name:
              'neue_webapp-0.1.1.zip',
            mimeType:
              'application/zip',
            size: '50000',
            modifiedTime:
              '2026-09-24T18:02:00Z',
          },
        ],
        {}
      );

    assert.equal(
      selected,
      null
    );
  }
);