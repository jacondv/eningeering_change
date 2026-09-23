env = self.env
EC = env['engineering.change'].with_context(active_test=False)
Line = env['engineering.change.checklist.line'].sudo()
targets = EC.search([('checklist_line_ids', '=', False)])
print("EC without checklist:", len(targets))
for rec in targets:
    Line.create([
        {'change_id': rec.id, 'section': s, 'sequence': seq, 'name': n}
        for s, seq, n in EC.DEFAULT_CHECKLIST_ITEMS
    ])
env.cr.commit()
print("Backfilled:", len(targets))
