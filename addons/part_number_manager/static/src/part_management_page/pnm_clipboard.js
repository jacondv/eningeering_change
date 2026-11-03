/** @odoo-module **/

// Tab-separated text, the way Excel/Sheets put cells on the clipboard: every
// row ends with a line break, so a blank row is an empty line rather than
// nothing, and a cell holding a tab or line break is wrapped in double quotes.

const LINE_BREAK = /\r\n|\r|\n/;
const TRAILING_LINE_BREAK = new RegExp(`(?:${LINE_BREAK.source})$`);
// A cell only counts as quoted when it holds a tab or line break, the one case
// where Excel quotes it, and its closing quote ends the cell - so that plain
// text such as `"3/4"` or `"3/4" hose` is taken as it is.
const CELL = /"((?:[^"]|"")*[\t\r\n](?:[^"]|"")*)"(?=[\t\r\n]|$)|[^\t\r\n]*/y;

export function parseClipboardRows(text) {
    const body = text.replace(TRAILING_LINE_BREAK, "");
    const rows = [[]];
    let position = 0;
    while (true) {
        CELL.lastIndex = position;
        const match = CELL.exec(body);
        rows.at(-1).push(match[1] === undefined ? match[0] : match[1].replace(/""/g, '"'));
        position = CELL.lastIndex;
        if (position >= body.length) {
            return rows;
        }
        if (body[position] === "\t") {
            position += 1;
        } else {
            position += body.startsWith("\r\n", position) ? 2 : 1;
            rows.push([]);
        }
    }
}

function formatCell(value) {
    return /[\t\r\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
}

export function formatClipboardRows(rows) {
    return rows.map((cells) => cells.map(formatCell).join("\t") + "\n").join("");
}
