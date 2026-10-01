# © 2014-2015 Savoir-faire Linux (<http://www.savoirfairelinux.com>).
# Copyright 2016 ACSONE SA/NV
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

import logging
import uuid

from odoo import fields, models

from ..client import CmisClient
from ..exceptions import CMISError, CMISObjectNotFoundError

_logger = logging.getLogger(__name__)


class CmisBackend(models.Model):
    _name = "cmis.backend"
    _description = "CMIS Backend"
    _order = "name desc"

    name = fields.Char(required=True)
    location = fields.Char(
        required=True,
        help="URL of the CMIS 1.1 browser binding service, e.g. "
        "http://localhost:8080/alfresco/api/-default-/public/cmis/versions/1.1/"
        "browser/",
    )
    username = fields.Char(required=True)
    password = fields.Char(required=True)
    timeout = fields.Integer(
        default=30, help="Timeout of the requests to the CMIS server, in seconds"
    )
    initial_directory_write = fields.Char(
        "Initial directory for writing", required=True, default="/"
    )

    _name_uniq = models.Constraint(
        "unique(name)",
        "CMIS Backend name must be unique!",
    )

    def get_cmis_client(self):
        """Get an initialized CmisClient using the CMIS browser binding"""
        self.ensure_one()
        return CmisClient(
            self.location,
            self.username,
            self.password,
            timeout=self.timeout or None,
        )

    def get_cmis_repository(self):
        """Return the default repository in the CMIS container"""
        self.ensure_one()
        return self.get_cmis_client().default_repository

    def check_directory_of_write(self):
        """Check that a document can be written in the initial directory"""
        self.ensure_one()
        folder = self.get_folder_by_path(
            self.initial_directory_write, create_if_not_found=False
        )
        if not folder:
            raise CMISError(
                self.env._(
                    "The directory %(path)s does not exist.",
                    path=self.initial_directory_write,
                )
            )
        document = folder.create_document(
            f"odoo-check-{uuid.uuid4().hex}.txt",
            b"hello, world",
            "text/plain",
        )
        document.delete()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "message": self.env._(
                    "Documents can be written in %(path)s.",
                    path=folder.path,
                ),
            },
        }

    def get_folder_by_path(
        self, path, create_if_not_found=True, cmis_parent_objectid=None
    ):
        """Return the folder at the given path, or False when it does not exist
        and ``create_if_not_found`` is False.

        :param path: absolute path, or relative to ``cmis_parent_objectid``
        :param cmis_parent_objectid: id of the folder the path is relative to
        """
        self.ensure_one()
        repo = self.get_cmis_repository()
        if cmis_parent_objectid:
            parent_path = repo.get_object(cmis_parent_objectid).get_paths()[0]
            path = f"{parent_path.rstrip('/')}/{path.lstrip('/')}"
        if not path.startswith("/"):
            path = f"/{path}"
        try:
            return repo.get_object_by_path(path)
        except CMISObjectNotFoundError:
            if not create_if_not_found:
                return False
        # The path doesn't exist and must be created, folder by folder
        folder = repo.get_root_folder()
        for part in filter(None, path.split("/")):
            child_path = f"{folder.path.rstrip('/')}/{part}"
            try:
                folder = repo.get_object_by_path(child_path)
            except CMISObjectNotFoundError:
                folder = folder.create_folder(part)
        return folder

    def sanitize_input(self, value):
        """Escape a value to use it in a CMIS query LIKE literal"""
        for char in ("\\", "'", "%", "_"):
            value = value.replace(char, f"\\{char}")
        return value

    def safe_query(self, query, file_name, repo):
        """Run ``query`` with ``file_name`` escaped in place of ``%s``"""
        return repo.query(query % self.sanitize_input(file_name))
