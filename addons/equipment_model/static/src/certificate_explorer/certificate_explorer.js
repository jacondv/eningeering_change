/** @odoo-module **/

import { Component, onWillStart, useState, markup } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";

export class CertificateExplorer extends Component {
    static template = "equipment_model.CertificateExplorer";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.dialog = useService("dialog");
        this.state = useState({
            nodes: [],
            expanded: {},
            selectedId: null,
            selectedRecord: null,
        });

        onWillStart(async () => {
            await this.loadTree();
        });
    }

    async loadTree() {
        const nodes = await this.orm.searchRead(
            "equipment.certificate",
            [],
            ["name", "parent_id", "sequence"],
            { order: "sequence, name" }
        );
        this.state.nodes = nodes;
    }

    get rootNodes() {
        return this.state.nodes
            .filter((n) => !n.parent_id)
            .sort((a, b) => a.sequence - b.sequence || a.name.localeCompare(b.name));
    }

    childrenOf(nodeId) {
        return this.state.nodes
            .filter((n) => n.parent_id && n.parent_id[0] === nodeId)
            .sort((a, b) => a.sequence - b.sequence || a.name.localeCompare(b.name));
    }

    isExpanded(nodeId) {
        return !!this.state.expanded[nodeId];
    }

    toggleExpand(nodeId, ev) {
        ev.stopPropagation();
        this.state.expanded[nodeId] = !this.state.expanded[nodeId];
    }

    onExpandAll() {
        const expanded = {};
        for (const node of this.state.nodes) {
            expanded[node.id] = true;
        }
        this.state.expanded = expanded;
    }

    onCollapseAll() {
        this.state.expanded = {};
    }

    async selectNode(nodeId) {
        this.state.selectedId = nodeId;
        const [record] = await this.orm.read("equipment.certificate", [nodeId], [
            "name",
            "complete_name",
            "description",
            "parent_id",
        ]);
        record.description = record.description ? markup(record.description) : "";
        this.state.selectedRecord = record;
    }

    async openForm(resId, defaultParentId) {
        const context = {};
        if (defaultParentId !== undefined) {
            context.default_parent_id = defaultParentId;
        }
        await this.action.doAction(
            {
                type: "ir.actions.act_window",
                res_model: "equipment.certificate",
                res_id: resId || false,
                views: [[false, "form"]],
                target: "new",
                context,
            },
            {
                onClose: async () => {
                    await this.loadTree();
                    if (this.state.selectedId) {
                        await this.selectNode(this.state.selectedId);
                    }
                },
            }
        );
    }

    onAddRoot() {
        this.openForm(false, false);
    }

    onAddChild(nodeId, ev) {
        ev.stopPropagation();
        this.state.expanded[nodeId] = true;
        this.openForm(false, nodeId);
    }

    onEditSelected() {
        if (this.state.selectedId) {
            this.openForm(this.state.selectedId);
        }
    }

    countDescendants(nodeId) {
        let count = 0;
        for (const child of this.childrenOf(nodeId)) {
            count += 1 + this.countDescendants(child.id);
        }
        return count;
    }

    onDelete(node, ev) {
        ev.stopPropagation();
        const descendantCount = this.countDescendants(node.id);
        const body =
            descendantCount > 0
                ? _t(
                      "Delete “%(name)s” and its %(count)s sub-item(s)? This cannot be undone.",
                      { name: node.name, count: descendantCount }
                  )
                : _t("Delete “%(name)s”? This cannot be undone.", { name: node.name });

        this.dialog.add(ConfirmationDialog, {
            title: _t("Delete item"),
            body,
            confirmLabel: _t("Delete"),
            confirmClass: "btn-danger",
            confirm: async () => {
                await this.orm.unlink("equipment.certificate", [node.id]);
                if (
                    this.state.selectedId === node.id ||
                    this.isDescendantOfDeleted(this.state.selectedId, node.id)
                ) {
                    this.state.selectedId = null;
                    this.state.selectedRecord = null;
                }
                await this.loadTree();
            },
            cancel: () => {},
        });
    }

    isDescendantOfDeleted(nodeId, deletedId) {
        if (!nodeId) {
            return false;
        }
        let current = this.state.nodes.find((n) => n.id === nodeId);
        while (current && current.parent_id) {
            if (current.parent_id[0] === deletedId) {
                return true;
            }
            current = this.state.nodes.find((n) => n.id === current.parent_id[0]);
        }
        return false;
    }
}

registry.category("actions").add("equipment_certificate_explorer", CertificateExplorer);
