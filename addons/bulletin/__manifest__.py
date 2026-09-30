{
    'name': 'Bulletin',
    'version': '19.0.1.0.0',
    'category': 'Productivity',
    'summary': 'Author bulletins (Safety, Design Change, Immediate Actions...) and print them to PDF',
    'description': """
Bulletin
========
Author bulletins made of reusable, freely-arrangeable sections, then export
to PDF.

- Section: a reusable header (e.g. "Subject", "Issue Description") that can
  be inserted into any Template. A section is either free-text (HTML) or an
  Approval & Signature block (prints the Approver's name, job title and a
  blank space to sign by hand).
- Template: a named bulletin type (e.g. "SAFETY BULLETIN") defining which
  sections it has and in what order. An Approval & Signature section can
  have a default Approver per template.
- Bulletin: an actual document. Picking a Template pre-fills its sections
  ready to fill in; document number is auto-generated as JE-B-YYMM-NN,
  resetting each month.
""",
    'author': 'Jacon',
    'license': 'LGPL-3',
    'depends': ['base', 'mail', 'hr', 'jacon_documents', 'jacon_core'],
    'data': [
        'security/bulletin_groups.xml',
        'security/ir.model.access.csv',
        'views/bulletin_section_views.xml',
        'views/bulletin_template_views.xml',
        'views/bulletin_bulletin_views.xml',
        'views/bulletin_menus.xml',
        'report/bulletin_report.xml',
        'report/bulletin_report_templates.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'bulletin/static/src/section_widget/bulletin_section_widget.js',
            'bulletin/static/src/section_widget/bulletin_section_widget.xml',
            'bulletin/static/src/section_widget/bulletin_section_widget.scss',
        ],
    },
    'installable': True,
    'application': False,
    'post_init_hook': 'post_init_hook',
}
