# © 2014-2015 Savoir-faire Linux (<http://www.savoirfairelinux.com>).
# Copyright 2016 ACSONE SA/NV
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from unittest import mock

from psycopg2 import IntegrityError

from odoo.tests import common
from odoo.tools import mute_logger

from ..client import CmisClient
from ..exceptions import CMISError
from .common import (
    BROWSER_URL,
    REPOSITORIES,
    ROOT_ID,
    ROOT_URL,
    FakeSession,
    cmis_object,
    make_response,
    not_found,
)


class TestCmisBackend(common.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vals = {
            "name": "Test cmis",
            "location": BROWSER_URL,
            "username": "admin",
            "password": "admin",
            "initial_directory_write": "/",
        }
        cls.backend = cls.env["cmis.backend"].create(cls.vals)

    def _mock_client(self, *responses):
        session = FakeSession(make_response(json_data=REPOSITORIES), *responses)
        client = CmisClient(BROWSER_URL, "admin", "admin", session=session)
        patcher = mock.patch.object(
            type(self.backend), "get_cmis_client", return_value=client
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        return session

    @mute_logger("odoo.sql_db")
    def test_unique_name(self):
        with self.assertRaises(IntegrityError):
            self.env["cmis.backend"].create(self.vals)

    def test_get_cmis_client(self):
        client = self.backend.get_cmis_client()
        self.assertEqual(client.url, BROWSER_URL)
        self.assertEqual(client.session.auth, ("admin", "admin"))
        self.assertEqual(client.timeout, 30)

    def test_get_folder_by_path_existing(self):
        self._mock_client(
            make_response(json_data=cmis_object("f1", "b", **{"cmis:path": "/a/b"}))
        )
        folder = self.backend.get_folder_by_path("/a/b")
        self.assertEqual(folder.id, "f1")

    def test_get_folder_by_path_not_found(self):
        self._mock_client(not_found())
        self.assertFalse(
            self.backend.get_folder_by_path("/a/b", create_if_not_found=False)
        )

    def test_get_folder_by_path_create(self):
        session = self._mock_client(
            not_found(),  # /a/b
            make_response(json_data=cmis_object(ROOT_ID, "root", **{"cmis:path": "/"})),
            make_response(json_data=cmis_object("a", "a", **{"cmis:path": "/a"})),
            not_found(),  # /a/b
            make_response(json_data=cmis_object("b", "b", **{"cmis:path": "/a/b"})),
        )
        folder = self.backend.get_folder_by_path("a/b")
        self.assertEqual(folder.id, "b")
        create = session.calls[-1]
        self.assertEqual((create[0], create[1]), ("POST", ROOT_URL))
        self.assertEqual(create[2]["data"]["objectId"], "a")
        self.assertEqual(create[2]["data"]["propertyValue[1]"], "b")

    def test_get_folder_by_path_relative(self):
        session = self._mock_client(
            make_response(json_data=cmis_object("p", "p", **{"cmis:path": "/p"})),
            make_response(json_data=cmis_object("c", "c", **{"cmis:path": "/p/c"})),
        )
        folder = self.backend.get_folder_by_path("c", cmis_parent_objectid="p")
        self.assertEqual(folder.id, "c")
        self.assertEqual(session.calls[-1][1], f"{ROOT_URL}/p/c")

    def test_check_directory_of_write(self):
        session = self._mock_client(
            make_response(json_data=cmis_object(ROOT_ID, "root", **{"cmis:path": "/"})),
            make_response(json_data=cmis_object("d1;1.0", "check", "cmis:document")),
            make_response(),
        )
        action = self.backend.check_directory_of_write()
        self.assertEqual(action["params"]["type"], "success")
        self.assertEqual(session.calls[-2][2]["data"]["cmisaction"], "createDocument")
        # the test document is removed
        self.assertEqual(session.calls[-1][2]["data"]["cmisaction"], "delete")
        self.assertEqual(session.calls[-1][2]["data"]["objectId"], "d1;1.0")

    def test_check_directory_of_write_missing(self):
        self._mock_client(not_found())
        with self.assertRaises(CMISError):
            self.backend.check_directory_of_write()

    def test_safe_query(self):
        repo = mock.Mock()
        self.backend.safe_query(
            "SELECT * FROM cmis:document WHERE cmis:name LIKE '%s'", "it's_50%", repo
        )
        repo.query.assert_called_once_with(
            "SELECT * FROM cmis:document WHERE cmis:name LIKE 'it\\'s\\_50\\%'"
        )
