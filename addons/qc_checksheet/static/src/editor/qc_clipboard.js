/** @odoo-module **/

import { escape } from "@web/core/utils/strings";

function linesToHtml(text) {
    const lines = text.split("\n").map((line) => line.trim()).filter(Boolean);
    return lines.map((line) => `<p>${escape(line)}</p>`).join("");
}

function tableCellText(cell) {
    cell.querySelectorAll("br").forEach((br) => br.replaceWith("\n"));
    const paragraphs = cell.querySelectorAll("p, li");
    if (paragraphs.length) {
        return [...paragraphs].map((p) => p.textContent.replace(/\s+/g, " ").trim()).join("\n");
    }
    return cell.textContent.replace(/[^\S\n]+/g, " ");
}

/**
 * Rows of cells if the clipboard holds a table copied from Word or Excel, else
 * null, so a plain paste (text, a single cell, an image) stays with the editor.
 * Each cell comes back as Html. Only the text is kept, because formatting
 * copied from Word or Excel doesn't survive the report's narrow columns well.
 *
 * @param {DataTransfer} clipboardData
 * @returns {string[][]|null}
 */
export function parseClipboardRows(clipboardData) {
    const html = clipboardData.getData("text/html");
    let rows = null;
    if (html && html.includes("<table")) {
        const table = new DOMParser().parseFromString(html, "text/html").querySelector("table");
        rows = [...table.rows].map((row) => [...row.cells].map(tableCellText));
    } else {
        const text = clipboardData.getData("text/plain");
        if (text.includes("\t")) {
            rows = text
                .replace(/\r/g, "")
                .split("\n")
                .filter((row) => row.trim())
                .map((row) => row.split("\t"));
        }
    }
    if (!rows || !rows.length || (rows.length === 1 && rows[0].length === 1)) {
        return null;
    }
    return rows.map((row) => row.map(linesToHtml));
}
