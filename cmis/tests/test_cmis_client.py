# Copyright 2026 tansadio
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

import datetime

import requests

from odoo.tests.common import BaseCase
from odoo.tools import mute_logger

from ..client import CmisClient, properties_data
from ..exceptions import (
    CMISConnectionError,
    CMISContentAlreadyExistsError,
    CMISError,
    CMISObjectNotFoundError,
)
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


class TestCmisClient(BaseCase):
    def _repository(self, *responses):
        session = FakeSession(make_response(json_data=REPOSITORIES), *responses)
        client = CmisClient(BROWSER_URL, "admin", "secret", session=session)
        return client.default_repository, session

    def test_default_repository(self):
        repo, session = self._repository()
        self.assertEqual(repo.id, "-default-")
        self.assertEqual(repo.root_folder_id, ROOT_ID)
        self.assertEqual(session.auth, ("admin", "secret"))
        self.assertEqual(session.calls[0][:2], ("GET", BROWSER_URL))

    def test_unknown_repository(self):
        session = FakeSession(make_response(json_data=REPOSITORIES))
        client = CmisClient(BROWSER_URL, "admin", "secret", session=session)
        with self.assertRaises(CMISError):
            client.get_repository("other")

    def test_properties_data(self):
        date = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
        self.assertEqual(
            properties_data(
                {
                    "cmis:name": "a",
                    "cmis:secondaryObjectTypeIds": ["P:cm:titled", "P:cm:author"],
                    "my:flag": True,
                    "my:date": date,
                    "my:unset": None,
                }
            ),
            {
                "propertyId[0]": "cmis:name",
                "propertyValue[0]": "a",
                "propertyId[1]": "cmis:secondaryObjectTypeIds",
                "propertyValue[1][0]": "P:cm:titled",
                "propertyValue[1][1]": "P:cm:author",
                "propertyId[2]": "my:flag",
                "propertyValue[2]": "true",
                "propertyId[3]": "my:date",
                "propertyValue[3]": "1767225600000",
                "propertyId[4]": "my:unset",
            },
        )

    def test_get_object_by_path(self):
        repo, session = self._repository(
            make_response(
                json_data=cmis_object("f1", "Mes Documents", **{"cmis:path": "/x"})
            )
        )
        folder = repo.get_object_by_path("Sites/Mes Documents")
        self.assertEqual(folder.id, "f1")
        self.assertTrue(folder.is_folder)
        method, url, kwargs = session.calls[1]
        self.assertEqual(url, f"{ROOT_URL}/Sites/Mes%20Documents")
        self.assertEqual(kwargs["params"]["cmisselector"], "object")
        self.assertEqual(kwargs["params"]["succinct"], "true")

    def test_object_not_found(self):
        repo, __ = self._repository(not_found("Object not found: /nope"))
        with self.assertRaises(CMISObjectNotFoundError) as error:
            repo.get_object_by_path("/nope")
        self.assertEqual(error.exception.status_code, 404)
        self.assertEqual(error.exception.cmis_exception, "objectNotFound")

    def test_content_already_exists(self):
        repo, __ = self._repository(
            make_response(
                409,
                {"exception": "contentAlreadyExists", "message": "already exists"},
            )
        )
        with self.assertRaises(CMISContentAlreadyExistsError):
            repo.create_folder(ROOT_ID, "existing")

    def test_authentication_failed(self):
        # Alfresco answers authentication errors with a web script body
        session = FakeSession(
            make_response(
                401,
                {"status": {"code": 401}, "message": "Authentication failed"},
                reason="Unauthorized",
            )
        )
        client = CmisClient(BROWSER_URL, "admin", "wrong", session=session)
        with self.assertRaises(CMISConnectionError) as error:
            client.get_repositories()
        self.assertEqual(error.exception.status_code, 401)

    @mute_logger("odoo.addons.cmis.client")
    def test_server_unreachable(self):
        session = FakeSession(requests.ConnectionError("refused"))
        client = CmisClient(BROWSER_URL, "admin", "secret", session=session)
        with self.assertRaises(CMISConnectionError):
            client.get_repositories()

    def test_create_folder(self):
        repo, session = self._repository(
            make_response(json_data=cmis_object("f2", "new"))
        )
        folder = repo.create_folder("parent;1.0", "new", {"cm:title": "New"})
        self.assertEqual(folder.name, "new")
        method, url, kwargs = session.calls[1]
        self.assertEqual((method, url), ("POST", ROOT_URL))
        data = kwargs["data"]
        self.assertEqual(data["cmisaction"], "createFolder")
        # ids with ';' are sent in the body, not in the URL
        self.assertEqual(data["objectId"], "parent;1.0")
        self.assertEqual(data["propertyValue[0]"], "cmis:folder")
        self.assertEqual(data["propertyValue[1]"], "new")
        self.assertEqual(data["propertyId[2]"], "cm:title")
        self.assertIsNone(kwargs["files"])

    def test_create_document(self):
        repo, session = self._repository(
            make_response(
                json_data=cmis_object(
                    "d1;1.0", "a.pdf", "cmis:document", **{"cmis:versionLabel": "1.0"}
                )
            )
        )
        document = repo.create_document(
            "f1", "a.pdf", b"%PDF", "application/pdf", versioning_state="major"
        )
        self.assertTrue(document.is_document)
        self.assertEqual(document.version_label, "1.0")
        kwargs = session.calls[1][2]
        self.assertEqual(kwargs["data"]["cmisaction"], "createDocument")
        # the fields of the multipart request are encoded in UTF-8
        self.assertEqual(kwargs["data"]["_charset_"], "UTF-8")
        self.assertEqual(kwargs["data"]["versioningState"], "major")
        self.assertEqual(
            kwargs["files"], {"content": ("a.pdf", b"%PDF", "application/pdf")}
        )

    def test_iter_children(self):
        repo, session = self._repository(
            make_response(
                json_data={
                    "objects": [{"object": cmis_object("c1", "one")}],
                    "hasMoreItems": True,
                    "numItems": 2,
                }
            ),
            make_response(
                json_data={
                    "objects": [{"object": cmis_object("c2", "two")}],
                    "hasMoreItems": False,
                    "numItems": 2,
                }
            ),
        )
        names = [child.name for child in repo.iter_children(ROOT_ID, page_size=1)]
        self.assertEqual(names, ["one", "two"])
        self.assertEqual(session.calls[2][2]["params"]["skipCount"], 1)

    def test_query(self):
        repo, session = self._repository(
            make_response(
                json_data={
                    "results": [cmis_object("f1", "Sites")],
                    "hasMoreItems": False,
                    "numItems": 1,
                }
            )
        )
        page = repo.query("SELECT * FROM cmis:folder WHERE cmis:name='Sites'")
        self.assertEqual(page.num_items, 1)
        self.assertEqual(page.objects[0].id, "f1")
        method, url, kwargs = session.calls[1]
        self.assertEqual(url, BROWSER_URL)
        self.assertEqual(kwargs["params"]["cmisselector"], "query")

    def test_get_content(self):
        repo, session = self._repository(make_response(content=b"hello"))
        self.assertEqual(repo.get_content("d1;1.0"), b"hello")
        self.assertEqual(session.calls[1][2]["params"]["cmisselector"], "content")

    def test_check_in(self):
        repo, session = self._repository(
            make_response(
                json_data=cmis_object(
                    "d1;2.0", "a.txt", "cmis:document", **{"cmis:versionLabel": "2.0"}
                )
            )
        )
        version = repo.check_in("d1;pwc", b"v2", "text/plain", comment="update")
        self.assertEqual(version.version_label, "2.0")
        data = session.calls[1][2]["data"]
        self.assertEqual(data["cmisaction"], "checkIn")
        self.assertEqual(data["objectId"], "d1;pwc")
        self.assertEqual(data["major"], "true")
        self.assertEqual(data["checkinComment"], "update")

    def test_document_paths(self):
        repo, __ = self._repository(
            make_response(
                json_data=[{"object": cmis_object("f1", "x", **{"cmis:path": "/a/x"})}]
            )
        )
        document = repo._object(cmis_object("d1", "doc.txt", "cmis:document"))
        self.assertEqual(document.get_paths(), ["/a/x/doc.txt"])
