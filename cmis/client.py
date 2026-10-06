# Copyright 2026 tansadio
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Minimal CMIS 1.1 client using the browser binding (JSON over HTTP).

It replaces the unmaintained ``cmislib`` library and only covers what Odoo
needs: navigation, folders and documents, queries, content and versioning.
All requests use succinct properties, so an object is a plain dict of
property values, e.g. ``{"cmis:objectId": "...", "cmis:name": "..."}``.

The specification of the binding is available at
http://docs.oasis-open.org/cmis/CMIS/v1.1/os/CMIS-v1.1-os.html#x1-5100005
"""

import datetime
import logging
from collections import namedtuple
from urllib.parse import quote

import requests

from .exceptions import CMIS_EXCEPTIONS, CMISConnectionError, CMISError

_logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30
DEFAULT_PAGE_SIZE = 100

CmisPage = namedtuple("CmisPage", ["objects", "has_more_items", "num_items"])
CmisPage.__doc__ = """One page of objects returned by a children or query call.

``num_items`` is the total number of items when the server knows it, else None.
"""


def _format_value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime.datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=datetime.UTC)
        return str(int(value.timestamp() * 1000))
    return str(value)


def properties_data(properties):
    """Encode properties as browser binding form fields (CMIS 1.1 §5.4.4.3).

    A list value is a multi-valued property, None unsets the property.
    """
    data = {}
    for index, (property_id, value) in enumerate(properties.items()):
        data[f"propertyId[{index}]"] = property_id
        if isinstance(value, list | tuple):
            for value_index, item in enumerate(value):
                data[f"propertyValue[{index}][{value_index}]"] = _format_value(item)
        elif value is not None:
            data[f"propertyValue[{index}]"] = _format_value(value)
    return data


class CmisClient:
    """Entry point: authenticate on a browser binding service URL."""

    def __init__(self, url, username, password, timeout=DEFAULT_TIMEOUT, session=None):
        self.url = url
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.auth = (username, password)

    def request(self, method, url, **kwargs):
        """Send a request and turn any error into a :class:`CMISError`"""
        kwargs.setdefault("timeout", self.timeout)
        try:
            response = self.session.request(method, url, **kwargs)
        except requests.RequestException as error:
            _logger.warning("CMIS request to %s failed: %s", url, error)
            raise CMISConnectionError(
                f"Unable to reach the CMIS server {url}: {error}"
            ) from error
        if response.status_code >= 400:
            raise self._error_from_response(response)
        return response

    def _error_from_response(self, response):
        try:
            body = response.json()
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        # CMIS errors are {"exception": ..., "message": ...}; authentication
        # errors raised before CMIS (Alfresco web scripts) have no exception
        cmis_exception = body.get("exception") or None
        message = body.get("message") or response.reason or "CMIS error"
        if response.status_code == 401:
            return CMISConnectionError(
                f"CMIS authentication failed: {message}",
                status_code=response.status_code,
            )
        error_class = CMIS_EXCEPTIONS.get(cmis_exception, CMISError)
        return error_class(
            message, cmis_exception=cmis_exception, status_code=response.status_code
        )

    def get_repositories(self):
        """Return the repositories infos, as a dict by repository id"""
        return self.request("GET", self.url).json()

    def get_repository(self, repository_id=None):
        """Return the given repository, or the first (default) one"""
        repositories = self.get_repositories()
        if not repositories:
            raise CMISError(f"No CMIS repository found at {self.url}")
        if repository_id is None:
            info = next(iter(repositories.values()))
        elif repository_id in repositories:
            info = repositories[repository_id]
        else:
            raise CMISError(f"CMIS repository {repository_id} not found")
        return CmisRepository(self, info)

    @property
    def default_repository(self):
        return self.get_repository()


class CmisRepository:
    """A CMIS repository, accessed through its browser binding URLs"""

    def __init__(self, client, info):
        self.client = client
        self.info = info
        self.id = info["repositoryId"]
        self.root_folder_id = info["rootFolderId"]
        self.root_folder_url = info["rootFolderUrl"]
        self.repository_url = info["repositoryUrl"]

    def __repr__(self):
        return f"<CmisRepository {self.id}>"

    # Low level helpers

    def _get(self, url, selector, object_id=None, **params):
        params["cmisselector"] = selector
        params.setdefault("succinct", "true")
        if object_id:
            params["objectId"] = object_id
        return self.client.request("GET", url, params=params)

    def _post(self, action, object_id=None, properties=None, content=None, **data):
        data["cmisaction"] = action
        data["succinct"] = "true"
        # without it, the servers decode the fields of the multipart requests
        # (with a content) as ISO-8859-1: "Mémoire" would be named "MÃ©moire"
        data["_charset_"] = "UTF-8"
        if object_id:
            # object ids may contain ';' (versions, pwc): send them in the body
            data["objectId"] = object_id
        if properties:
            data.update(properties_data(properties))
        data = {key: _format_value(value) for key, value in data.items()}
        files = None
        if content is not None:
            filename, payload, mime_type = content
            files = {"content": (filename, payload, mime_type)}
        return self.client.request("POST", self.root_folder_url, data=data, files=files)

    def _object(self, json_object):
        return CmisObject(self, json_object.get("succinctProperties", {}))

    def _page(self, json_page, key):
        if key == "objects":
            items = [item["object"] for item in json_page.get("objects", [])]
        else:
            items = json_page.get(key, [])
        return CmisPage(
            [self._object(item) for item in items],
            json_page.get("hasMoreItems", False),
            json_page.get("numItems"),
        )

    # Read

    def get_root_folder(self):
        return self.get_object(self.root_folder_id)

    def get_object(self, object_id):
        response = self._get(self.root_folder_url, "object", object_id)
        return self._object(response.json())

    def get_object_by_path(self, path):
        if not path.startswith("/"):
            path = f"/{path}"
        url = self.root_folder_url + quote(path)
        return self._object(self._get(url, "object").json())

    def get_children(self, folder_id, max_items=DEFAULT_PAGE_SIZE, skip_count=0):
        response = self._get(
            self.root_folder_url,
            "children",
            folder_id,
            maxItems=max_items,
            skipCount=skip_count,
        )
        return self._page(response.json(), "objects")

    def iter_children(self, folder_id, page_size=DEFAULT_PAGE_SIZE):
        """Iterate over all the children of a folder, page after page"""
        skip_count = 0
        while True:
            page = self.get_children(folder_id, page_size, skip_count)
            yield from page.objects
            if not page.has_more_items or not page.objects:
                return
            skip_count += len(page.objects)

    def get_parents(self, object_id):
        response = self._get(self.root_folder_url, "parents", object_id)
        return [self._object(item["object"]) for item in response.json()]

    def get_content(self, object_id):
        """Return the content stream of a document, as bytes"""
        response = self.client.request(
            "GET",
            self.root_folder_url,
            params={"objectId": object_id, "cmisselector": "content"},
        )
        return response.content

    def query(self, statement, max_items=DEFAULT_PAGE_SIZE, skip_count=0):
        """Run a CMIS SQL query. Values must be escaped by the caller."""
        response = self._get(
            self.repository_url,
            "query",
            q=statement,
            maxItems=max_items,
            skipCount=skip_count,
            searchAllVersions="false",
        )
        return self._page(response.json(), "results")

    # Write

    def create_folder(self, parent_id, name, properties=None):
        values = {"cmis:objectTypeId": "cmis:folder", "cmis:name": name}
        values.update(properties or {})
        response = self._post("createFolder", parent_id, values)
        return self._object(response.json())

    def create_document(
        self,
        parent_id,
        name,
        content=b"",
        mime_type="application/octet-stream",
        properties=None,
        versioning_state=None,
    ):
        """Create a document. ``versioning_state`` is one of none, checkedout,
        major or minor (server default when not set)."""
        values = {"cmis:objectTypeId": "cmis:document", "cmis:name": name}
        values.update(properties or {})
        extra = {}
        if versioning_state:
            extra["versioningState"] = versioning_state
        response = self._post(
            "createDocument",
            parent_id,
            values,
            content=(name, content, mime_type),
            **extra,
        )
        return self._object(response.json())

    def update_properties(self, object_id, properties):
        response = self._post("update", object_id, properties)
        return self._object(response.json())

    def set_content(self, object_id, content, mime_type, filename="content"):
        response = self._post(
            "setContent",
            object_id,
            content=(filename, content, mime_type),
            overwriteFlag=True,
        )
        return self._object(response.json())

    def move(self, object_id, source_folder_id, target_folder_id):
        response = self._post(
            "move",
            object_id,
            sourceFolderId=source_folder_id,
            targetFolderId=target_folder_id,
        )
        return self._object(response.json())

    def delete(self, object_id, all_versions=True):
        self._post("delete", object_id, allVersions=all_versions)

    def delete_tree(self, folder_id, all_versions=True, continue_on_failure=False):
        self._post(
            "deleteTree",
            folder_id,
            allVersions=all_versions,
            continueOnFailure=continue_on_failure,
        )

    # Versioning

    def check_out(self, object_id):
        """Check out a document, return its private working copy"""
        return self._object(self._post("checkOut", object_id).json())

    def cancel_check_out(self, pwc_id):
        self._post("cancelCheckOut", pwc_id)

    def check_in(
        self,
        pwc_id,
        content=None,
        mime_type="application/octet-stream",
        major=True,
        comment=None,
        properties=None,
        filename="content",
    ):
        """Check in a private working copy, return the new version"""
        extra = {"major": major}
        if comment:
            extra["checkinComment"] = comment
        response = self._post(
            "checkIn",
            pwc_id,
            properties,
            content=(filename, content, mime_type) if content is not None else None,
            **extra,
        )
        return self._object(response.json())


class CmisObject:
    """A CMIS object (folder or document) and its succinct properties"""

    def __init__(self, repository, properties):
        self.repository = repository
        self.properties = properties

    def __repr__(self):
        return f"<CmisObject {self.base_type_id} {self.name} ({self.id})>"

    def __eq__(self, other):
        return isinstance(other, CmisObject) and self.id == other.id

    def __hash__(self):
        return hash(self.id)

    @property
    def id(self):
        return self.properties.get("cmis:objectId")

    @property
    def name(self):
        return self.properties.get("cmis:name")

    @property
    def base_type_id(self):
        return self.properties.get("cmis:baseTypeId")

    @property
    def object_type_id(self):
        return self.properties.get("cmis:objectTypeId")

    @property
    def is_folder(self):
        return self.base_type_id == "cmis:folder"

    @property
    def is_document(self):
        return self.base_type_id == "cmis:document"

    @property
    def path(self):
        """Path of a folder (documents have no path, see get_paths)"""
        return self.properties.get("cmis:path")

    @property
    def parent_id(self):
        return self.properties.get("cmis:parentId")

    @property
    def mime_type(self):
        return self.properties.get("cmis:contentStreamMimeType")

    @property
    def version_label(self):
        return self.properties.get("cmis:versionLabel")

    def refresh(self):
        self.properties = self.repository.get_object(self.id).properties
        return self

    def get_paths(self):
        """All the paths of the object (a document can be in several folders)"""
        if self.is_folder:
            return [self.path]
        return [
            f"{parent.path.rstrip('/')}/{self.name}"
            for parent in self.repository.get_parents(self.id)
        ]

    def get_children(self, max_items=DEFAULT_PAGE_SIZE, skip_count=0):
        return self.repository.get_children(self.id, max_items, skip_count)

    def iter_children(self, page_size=DEFAULT_PAGE_SIZE):
        return self.repository.iter_children(self.id, page_size)

    def create_folder(self, name, properties=None):
        return self.repository.create_folder(self.id, name, properties)

    def create_document(self, name, content=b"", mime_type=None, **kwargs):
        return self.repository.create_document(
            self.id,
            name,
            content,
            mime_type or "application/octet-stream",
            **kwargs,
        )

    def get_content(self):
        return self.repository.get_content(self.id)

    def update_properties(self, properties):
        self.properties = self.repository.update_properties(
            self.id, properties
        ).properties
        return self

    def move(self, source_folder_id, target_folder_id):
        return self.repository.move(self.id, source_folder_id, target_folder_id)

    def delete(self, all_versions=True):
        self.repository.delete(self.id, all_versions)

    def delete_tree(self, all_versions=True, continue_on_failure=False):
        self.repository.delete_tree(self.id, all_versions, continue_on_failure)

    def check_out(self):
        return self.repository.check_out(self.id)
