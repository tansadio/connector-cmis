## 19.0.1.0.0

Migration to Odoo 19.0.

The `cmislib` library, no longer maintained, is replaced by an internal
client for the CMIS 1.1 browser binding (`odoo.addons.cmis.client`), based on
`requests`. `cmis.backend.get_cmis_client()` and `get_cmis_repository()` now
return objects of this client, and CMIS errors are raised as `CMISError`
subclasses (`CMISObjectNotFoundError`, `CMISContentAlreadyExistsError`...).
The backend location must be the URL of the browser binding service.

## 11.0.1.0.0

First official version for Odoo 11.0.
