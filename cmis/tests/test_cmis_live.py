# Copyright 2026 tansadio
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Tests against a real CMIS server, run only when it is configured with:

- ``CMIS_TEST_LOCATION``: browser binding URL, e.g.
  http://localhost:8080/alfresco/api/-default-/public/cmis/versions/1.1/browser/
- ``CMIS_TEST_USERNAME`` and ``CMIS_TEST_PASSWORD`` (default admin / admin)
"""

import os
import unittest
import uuid

from odoo.tests.common import BaseCase

from ..client import CmisClient
from ..exceptions import CMISContentAlreadyExistsError, CMISObjectNotFoundError

LOCATION = os.environ.get("CMIS_TEST_LOCATION")


@unittest.skipUnless(LOCATION, "CMIS_TEST_LOCATION is not set")
class TestCmisLive(BaseCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        client = CmisClient(
            LOCATION,
            os.environ.get("CMIS_TEST_USERNAME", "admin"),
            os.environ.get("CMIS_TEST_PASSWORD", "admin"),
        )
        cls.repo = client.default_repository
        cls.folder = cls.repo.get_root_folder().create_folder(
            f"odoo-cmis-test-{uuid.uuid4().hex}"
        )

    @classmethod
    def tearDownClass(cls):
        cls.folder.delete_tree()
        super().tearDownClass()

    def test_folders_and_documents(self):
        sub = self.folder.create_folder("Sous dossier é")
        self.assertEqual(
            self.repo.get_object_by_path(f"{self.folder.path}/Sous dossier é"), sub
        )
        with self.assertRaises(CMISContentAlreadyExistsError):
            self.folder.create_folder("Sous dossier é")
        document = sub.create_document("a.txt", b"v1", "text/plain")
        self.assertEqual(document.get_content(), b"v1")
        self.assertEqual(document.get_paths(), [f"{sub.path}/a.txt"])
        self.assertEqual([child.name for child in sub.iter_children()], ["a.txt"])
        document.update_properties({"cmis:description": "hello"})
        self.assertEqual(document.refresh().properties["cmis:description"], "hello")
        document.delete()
        with self.assertRaises(CMISObjectNotFoundError):
            self.repo.get_object(document.id)

    def test_versioning(self):
        document = self.folder.create_document(
            "versioned.txt", b"v1", "text/plain", versioning_state="major"
        )
        pwc = document.check_out()
        version = self.repo.check_in(pwc.id, b"v2", "text/plain", comment="v2")
        self.assertEqual(version.version_label, "2.0")
        self.assertEqual(version.get_content(), b"v2")

    def test_query(self):
        name = self.folder.name
        page = self.repo.query(
            f"SELECT cmis:objectId FROM cmis:folder WHERE cmis:name = '{name}'"
        )
        self.assertEqual([obj.id for obj in page.objects], [self.folder.id])
