/**
 * Parallax logbook - a free Google Apps Script web app.
 *
 * Receives events from Parallax, adds each one as a row to this Google Sheet
 * (one tab per kind: Messages, Research, Chats) and emails the Sheet's owner.
 *
 * Setup: see "Activity log and messages" in the README.
 */

// Paste the same random string you put in PARALLAX_LOG_TOKEN. Requests without it are ignored.
const TOKEN = "PASTE-YOUR-PARALLAX_LOG_TOKEN-HERE";

// false = email only visitor messages (feedback, suggestions, reach-outs); research and chats are still logged.
// true = an email for every event.
const EMAIL_EVERYTHING = false;

const TABS = { message: "Messages", research: "Research", chat: "Chats" };

function doPost(e) {
  try {
    const body = JSON.parse(e.postData.contents);
    if (body.token !== TOKEN) return reply({ ok: false, error: "unauthorised" });

    const kind = String(body.kind || "other");
    const data = body.data || {};
    addRow(TABS[kind] || "Other", data);

    if (kind === "message" || EMAIL_EVERYTHING) {
      try {
        sendEmail(kind, data);
      } catch (mailError) {
        // Gmail's free daily limit may be reached: the row is still saved, so don't fail.
        console.warn("Email not sent: " + mailError);
      }
    }
    return reply({ ok: true });
  } catch (error) {
    console.error(error);
    return reply({ ok: false, error: String(error) });
  }
}

function addRow(tabName, data) {
  const book = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = book.getSheetByName(tabName) || book.insertSheet(tabName);
  const keys = Object.keys(data);

  if (sheet.getLastRow() === 0) {
    sheet.appendRow(["Time"].concat(keys));
    sheet.setFrozenRows(1);
  }
  let headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];

  // A field the sheet hasn't seen before gets a new column at the end, so nothing is ever dropped.
  const missing = keys.filter((key) => headers.indexOf(key) === -1);
  if (missing.length) {
    sheet.getRange(1, headers.length + 1, 1, missing.length).setValues([missing]);
    headers = headers.concat(missing);
  }
  // Columns follow the header row, so the order of fields never matters.
  const row = headers.map((header, i) => (i === 0 ? new Date() : safe(data[header])));
  sheet.appendRow(row);
}

// Visitor text that starts with = + - @ would run as a spreadsheet formula. Store it as plain text.
function safe(value) {
  if (value === undefined || value === null) return "";
  const text = String(value);
  return /^[=+\-@]/.test(text) ? "'" + text : text;
}

function sendEmail(kind, data) {
  const lines = Object.keys(data).map((key) => key + ": " + data[key]);
  const subjects = {
    message: "[Parallax] " + (data.type || "Message") + " from " + (data.name || "a visitor"),
    research: "[Parallax] Research: " + String(data.question || "").slice(0, 80),
    chat: "[Parallax] Chat: " + String(data.question || "").slice(0, 80),
  };
  const email = {
    to: Session.getEffectiveUser().getEmail(),
    subject: subjects[kind] || "[Parallax] " + kind,
    body: lines.join("\n\n"),
  };
  // Hitting "Reply" answers the visitor directly, when they left a valid email.
  if (kind === "message" && /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(data.email || "")) {
    email.replyTo = data.email;
  }
  MailApp.sendEmail(email);
}

function reply(object) {
  return ContentService.createTextOutput(JSON.stringify(object)).setMimeType(ContentService.MimeType.JSON);
}
