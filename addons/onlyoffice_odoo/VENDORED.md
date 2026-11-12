# Vendored third-party module

`onlyoffice_odoo` is the official ONLYOFFICE connector, copied unchanged from
https://github.com/ONLYOFFICE/onlyoffice_odoo (branch `19.0`, module version 6.4.0,
commit e21813606c5af15421ccf38c4ac0a67e5c264692). LGPL-3, see `__manifest__.py`,
`LICENSE.repo` and `3rd-Party.license`.

Rules:
- Do not edit files in this folder. Jacon-specific behaviour belongs in `jacon_office`.
- To upgrade, replace the whole folder with the new upstream module, update this file
  (version and commit), and run the `jacon_office` tests.
- Needs the `pyjwt` Python package (installed by the Dockerfile as `python3-jwt`).
