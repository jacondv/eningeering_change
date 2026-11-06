/** @odoo-module **/

const ITEM_COLUMNS = ["description", "acceptance", "note"];
const IMG_SRC_RE = /<img\b[^>]*?\bsrc="([^"]*)"/gi;
// An image's file checksum, out of /web/image/<id>-<checksum>/...: each Revision
// holds its own copy of an image, so only the file tells whether it changed.
const IMAGE_CHECKSUM_RE = /\/web\/image\/\d+-([0-9a-f]+)/;

export function htmlToText(html) {
    return new DOMParser()
        .parseFromString(html || "", "text/html")
        .body.textContent.replace(/\s+/g, " ")
        .trim();
}

/** What a cell says, ignoring formatting: its words and its images. */
function signature(html) {
    const images = [...(html || "").matchAll(IMG_SRC_RE)].map(
        ([, src]) => src.match(IMAGE_CHECKSUM_RE)?.[1] || src
    );
    return `${htmlToText(html)}\u0000${images.join(",")}`;
}

function describe(html) {
    const text = htmlToText(html);
    const images = (html || "").match(IMG_SRC_RE)?.length || 0;
    if (images) {
        return `${text}${text ? " " : ""}[${images} image${images > 1 ? "s" : ""}]`;
    }
    return text || "(empty)";
}

function groupTitle(group) {
    return htmlToText(group.name) || "Untitled Group";
}

/**
 * What `current` changed compared with `base`, row by row. Rows are matched by
 * line_key, which a row keeps from one Revision to the next, so inserting or
 * reordering rows doesn't read as edits. A row without a key is new.
 *
 * Works either way round: comparing with a later Revision tells what that later
 * one would add, change or remove.
 */
export function compareSheets(base, current) {
    const baseGroupsByKey = new Map(base.groups.map((group) => [group.line_key, group]));
    const baseItemsByKey = new Map();
    for (const group of base.groups) {
        for (const item of group.items) {
            baseItemsByKey.set(item.line_key, { item, group });
        }
    }

    const result = {
        groups: new Map(),
        items: new Map(),
        removedItems: new Map(),
        removedGroups: [],
        header: null,
        positions: { added: new Set(), removed: [] },
        counts: { added: 0, changed: 0, removed: 0, moved: 0 },
    };
    const { counts } = result;
    const keptGroupKeys = new Set();
    const keptItemUids = new Map();

    for (const group of current.groups) {
        const baseGroup = group.line_key && baseGroupsByKey.get(group.line_key);
        if (!baseGroup) {
            result.groups.set(group.uid, { status: "added" });
            counts.added++;
        } else {
            keptGroupKeys.add(group.line_key);
            if (signature(baseGroup.name) !== signature(group.name)) {
                result.groups.set(group.uid, { status: "changed", old: describe(baseGroup.name) });
                counts.changed++;
            }
        }
        for (const item of group.items) {
            const match = item.line_key && baseItemsByKey.get(item.line_key);
            if (!match) {
                result.items.set(item.uid, { status: "added", changed: {} });
                counts.added++;
                continue;
            }
            keptItemUids.set(item.line_key, { uid: item.uid, groupKey: group.line_key });
            const changed = {};
            for (const field of ITEM_COLUMNS) {
                if (signature(match.item[field]) !== signature(item[field])) {
                    changed[field] = describe(match.item[field]);
                }
            }
            const movedFrom = match.group.line_key !== group.line_key ? groupTitle(match.group) : "";
            const isChanged = Object.keys(changed).length > 0;
            counts.changed += isChanged ? 1 : 0;
            counts.moved += movedFrom ? 1 : 0;
            if (isChanged || movedFrom) {
                result.items.set(item.uid, { status: isChanged ? "changed" : "", changed, movedFrom });
            }
        }
    }

    // Removed rows go back where they were: after the row that came before them.
    const currentGroupsByKey = new Map(current.groups.map((group) => [group.line_key, group]));
    for (const baseGroup of base.groups) {
        const group = keptGroupKeys.has(baseGroup.line_key) && currentGroupsByKey.get(baseGroup.line_key);
        const ghosts = [];
        let after = null;
        for (const item of baseGroup.items) {
            const kept = keptItemUids.get(item.line_key);
            if (kept) {
                if (group && kept.groupKey === group.line_key) {
                    after = kept.uid;
                }
                continue;
            }
            ghosts.push({ after, item });
            counts.removed++;
        }
        if (group) {
            if (ghosts.length) {
                result.removedItems.set(group.uid, ghosts);
            }
        } else {
            result.removedGroups.push({ group: baseGroup, title: groupTitle(baseGroup), items: ghosts.map((g) => g.item) });
            counts.removed++;
        }
    }

    if ((base.name || "").trim() !== (current.name || "").trim()) {
        result.header = base.name || "(empty)";
    }

    const basePositions = base.positions.map((line) => line.position.trim());
    const unmatched = [...basePositions];
    current.positions.forEach((line, index) => {
        const at = unmatched.indexOf(line.position.trim());
        if (at >= 0) {
            unmatched.splice(at, 1);
        } else {
            result.positions.added.add(index);
        }
    });
    result.positions.removed = unmatched;
    return result;
}

/**
 * The rows of one current Group with the removed ones put back in: each entry
 * is either { item, number } as in the editor, or { ghost: item }.
 */
export function rowsWithRemoved(entryItems, ghosts) {
    if (!ghosts?.length) {
        return entryItems;
    }
    const placed = new Set();
    const rows = [];
    const placeAfter = (uid) => {
        ghosts.forEach((ghost, index) => {
            if (!placed.has(index) && ghost.after === uid) {
                placed.add(index);
                rows.push({ ghost: ghost.item, key: `ghost_${ghost.item.line_key}` });
            }
        });
    };
    placeAfter(null);
    for (const row of entryItems) {
        rows.push(row);
        placeAfter(row.item.uid);
    }
    // The row they followed has moved to another Group.
    ghosts.forEach((ghost, index) => {
        if (!placed.has(index)) {
            rows.push({ ghost: ghost.item, key: `ghost_${ghost.item.line_key}` });
        }
    });
    return rows;
}
