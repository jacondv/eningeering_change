/** @odoo-module **/

import { Component, useRef, useState } from "@odoo/owl";
import { DateTimeInput } from "@web/core/datetime/datetime_input";
import { Dialog } from "@web/core/dialog/dialog";
import { deserializeDate, serializeDate } from "@web/core/l10n/dates";
import { post } from "@web/core/network/http_service";
import { useService } from "@web/core/utils/hooks";

const { DateTime } = luxon;

const ALLOWED_EXTENSIONS = [".pdf", ".jpg", ".jpeg", ".png"];
const SCAN_DATE_FORMAT = "dd-MMM-yyyy";
// Under this there is little to save, so the options to reduce the size aren't offered.
const REDUCE_FROM_BYTES = 1024 * 1024;
// The ways to reduce a scan, as the server has them (see LEVELS in models/qc_scan_files.py).
const LEVELS = [
    {
        key: "standard",
        label: "Standard (recommended)",
        hint: "Pictures at 200 dpi, colour kept. Easy to read, much smaller.",
    },
    {
        key: "strong",
        label: "Strong",
        hint: "Pictures at 110 dpi in grey. The smallest: writing and signatures stay readable, colour goes.",
    },
];

/** 1536 -> "1.5 KB". */
export function humanSize(bytes) {
    let value = bytes;
    for (const unit of ["B", "KB"]) {
        if (value < 1024) {
            return unit === "B" ? `${Math.round(value)} ${unit}` : `${value.toFixed(1)} ${unit}`;
        }
        value /= 1024;
    }
    return `${value.toFixed(1)} MB`;
}

/**
 * Upload the signed scan of a Job's check sheet: PDF, JPG or PNG files up to the size in Settings, the day
 * the Job was inspected, and, if the files are big, a choice of how far to reduce their size. The choice is
 * offered as soon as the files are picked and nothing is reduced until Upload: "Show sizes" asks the server
 * what each way would leave, which is the real result, not a guess, but only when the user wants to know.
 * The files go to the server as they are; reducing happens there.
 */
export class QcScanDialog extends Component {
    static template = "qc_checksheet.ScanDialog";
    static components = { Dialog, DateTimeInput };
    static props = {
        close: Function,
        jobSheetId: Number,
        typeName: String,
        revision: Number,
        // {max_file_size, max_files}, from the server's Settings.
        limits: Object,
        onUploaded: Function,
    };

    setup() {
        this.notification = useService("notification");
        this.input = useRef("fileInput");
        this.state = useState({
            files: [],
            // Plain "YYYY-MM-DD": a luxon object doesn't survive being made reactive.
            checkDate: serializeDate(DateTime.local()),
            note: "",
            // "none", or the key of one of LEVELS. Standard is picked for big files until the user chooses.
            reduce: "none",
            // {loading, items: [{standard: {estimated_size, reduced}, strong: {...}}] | null, error}
            estimate: { loading: false, items: null, error: "" },
            uploading: false,
            error: "",
        });
        this.estimateRequest = 0;
        this.userChoseReduce = false;
    }

    get levels() {
        return LEVELS;
    }

    get dateFormat() {
        return SCAN_DATE_FORMAT;
    }

    get maxSizeText() {
        return humanSize(this.props.limits.max_file_size);
    }

    get checkDateValue() {
        return this.state.checkDate ? deserializeDate(this.state.checkDate) : false;
    }

    get isFuture() {
        return !!this.state.checkDate && this.state.checkDate > serializeDate(DateTime.local());
    }

    get totalSize() {
        return this.state.files.reduce((sum, item) => sum + item.file.size, 0);
    }

    /** Big enough that reducing is worth offering. */
    get canReduce() {
        return this.totalSize > REDUCE_FROM_BYTES;
    }

    /** What all the files weigh once reduced at this level, or null before the estimate is in. */
    totalAfter(level) {
        const items = this.state.estimate.items;
        return items ? items.reduce((sum, item) => sum + item[level].estimated_size, 0) : null;
    }

    savedPercent(level) {
        const after = this.totalAfter(level);
        return after === null || !this.totalSize ? 0 : Math.round((1 - after / this.totalSize) * 100);
    }

    /** The column of sizes after reducing: only once the user asked for the estimate. */
    get showAfter() {
        return this.state.reduce !== "none" && (this.state.estimate.loading || !!this.state.estimate.items);
    }

    get isBlocked() {
        return (
            this.state.uploading ||
            !this.state.files.length ||
            !this.state.checkDate ||
            this.isFuture ||
            (this.state.reduce !== "none" && this.state.estimate.loading)
        );
    }

    humanSize(bytes) {
        return humanSize(bytes);
    }

    /** What reducing at the chosen level leaves of the file at this position, once the estimate is in. */
    after(index) {
        return this.state.reduce === "none" ? null : this.state.estimate.items?.[index]?.[this.state.reduce] || null;
    }

    openPicker() {
        this.input.el.click();
    }

    onFilesPicked(ev) {
        const { max_file_size: maxSize, max_files: maxFiles } = this.props.limits;
        const rejected = [];
        const files = [...this.state.files];
        for (const file of ev.target.files) {
            const extension = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
            if (!ALLOWED_EXTENSIONS.includes(extension)) {
                rejected.push(`${file.name}: not a PDF, JPG or PNG file`);
            } else if (file.size > maxSize) {
                rejected.push(`${file.name}: ${humanSize(file.size)}, over the ${humanSize(maxSize)} a file may be`);
            } else if (files.length >= maxFiles) {
                rejected.push(`${file.name}: at most ${maxFiles} files at a time`);
            } else if (!file.size) {
                rejected.push(`${file.name}: empty`);
            } else {
                files.push({ file });
            }
        }
        ev.target.value = "";
        this.state.files = files;
        this.state.error = rejected.join("\n");
        this.filesChanged();
    }

    removeFile(index) {
        this.state.files.splice(index, 1);
        this.filesChanged();
    }

    chooseReduce(level) {
        this.userChoseReduce = true;
        this.state.reduce = level;
    }

    onDateChange(value) {
        this.state.checkDate = value ? serializeDate(value) : "";
    }

    formData(extra = {}) {
        const data = new FormData();
        data.append("csrf_token", odoo.csrf_token);
        for (const [key, value] of Object.entries(extra)) {
            data.append(key, value);
        }
        for (const { file } of this.state.files) {
            data.append("ufile", file, file.name);
        }
        return data;
    }

    /**
     * The files changed: an earlier estimate no longer holds. Big enough to be worth reducing, the choice is
     * offered at once with Standard picked, unless the user already chose; nothing is run.
     */
    filesChanged() {
        this.estimateRequest++;
        this.state.estimate = { loading: false, items: null, error: "" };
        if (!this.canReduce) {
            this.state.reduce = "none";
        } else if (!this.userChoseReduce) {
            this.state.reduce = "standard";
        }
    }

    /** "Show sizes": asks the server what each way of reducing would leave of the files as they are now. */
    async runEstimate() {
        const request = ++this.estimateRequest;
        this.state.estimate = { loading: true, items: null, error: "" };
        let result;
        try {
            result = await post("/qc_checksheet/scan/estimate", this.formData());
        } catch (error) {
            result = { error: error.message || "The estimate failed." };
        }
        if (request !== this.estimateRequest) {
            return;
        }
        this.state.estimate = {
            loading: false,
            items: result.error ? null : result.files,
            error: result.error || "",
        };
    }

    async upload() {
        if (this.isBlocked) {
            return;
        }
        this.state.uploading = true;
        this.state.error = "";
        try {
            const result = await post(
                "/qc_checksheet/scan/upload",
                this.formData({
                    job_sheet_id: this.props.jobSheetId,
                    check_date: this.state.checkDate,
                    note: this.state.note,
                    reduce: this.state.reduce,
                })
            );
            if (result.error) {
                this.state.error = result.error;
                return;
            }
            this.notification.add(`${this.state.files.length} file(s) uploaded`, { type: "success" });
            this.props.close();
            await this.props.onUploaded();
        } catch (error) {
            this.state.error = error.message || "The upload failed.";
        } finally {
            this.state.uploading = false;
        }
    }
}
