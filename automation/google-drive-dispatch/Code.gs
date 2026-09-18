/**
 * Direkte Benachrichtigung vom privaten Google-Drive-Codeeingang an GitHub.
 *
 * Einmal installieren: In script.google.com ein neues Projekt anlegen, diese
 * Datei einfügen, unter Projekteinstellungen das Script-Property
 * GITHUB_DISPATCH_TOKEN setzen und danach install() einmal ausführen.
 */
const DRIVE_IMPORT_FOLDER_ID = '1-mdRS3emTfYNrsdtL_dpz9iKqjDha8bF';
const GITHUB_REPOSITORY = 'Parrrrd/home-assistant-webapps';
const DISPATCH_EVENT = 'google_drive_package';

function install() {
  ScriptApp.getProjectTriggers()
    .filter((trigger) => trigger.getHandlerFunction() === 'notifyGithub')
    .forEach((trigger) => ScriptApp.deleteTrigger(trigger));
  ScriptApp.newTrigger('notifyGithub').timeBased().everyMinutes(1).create();
  notifyGithub();
}

function notifyGithub() {
  const token = PropertiesService.getScriptProperties().getProperty('GITHUB_DISPATCH_TOKEN');
  if (!token) throw new Error('Das Script-Property GITHUB_DISPATCH_TOKEN fehlt.');

  const folder = DriveApp.getFolderById(DRIVE_IMPORT_FOLDER_ID);
  const files = folder.getFiles();
  let latest = null;
  while (files.hasNext()) {
    const file = files.next();
    if (file.getMimeType() !== 'application/zip') continue;
    if (!latest || file.getLastUpdated().getTime() > latest.getLastUpdated().getTime()) latest = file;
  }
  if (!latest) return;

  const marker = `${latest.getId()}:${latest.getLastUpdated().getTime()}`;
  const properties = PropertiesService.getScriptProperties();
  if (properties.getProperty('LAST_DISPATCHED_PACKAGE') === marker) return;

  const response = UrlFetchApp.fetch(`https://api.github.com/repos/${GITHUB_REPOSITORY}/dispatches`, {
    method: 'post',
    contentType: 'application/json',
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
    },
    payload: JSON.stringify({
      event_type: DISPATCH_EVENT,
      client_payload: { file_id: latest.getId() },
    }),
    muteHttpExceptions: true,
  });
  if (response.getResponseCode() !== 204) {
    throw new Error(`GitHub-Benachrichtigung fehlgeschlagen (${response.getResponseCode()}): ${response.getContentText()}`);
  }
  properties.setProperty('LAST_DISPATCHED_PACKAGE', marker);
}
