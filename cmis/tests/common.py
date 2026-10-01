# Copyright 2026 tansadio
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

import json

import requests

BROWSER_URL = "http://alfresco/alfresco/api/-default-/public/cmis/versions/1.1/browser"
ROOT_URL = f"{BROWSER_URL}/root"
ROOT_ID = "root-id"

REPOSITORIES = {
    "-default-": {
        "repositoryId": "-default-",
        "rootFolderId": ROOT_ID,
        "rootFolderUrl": ROOT_URL,
        "repositoryUrl": BROWSER_URL,
        "productName": "Alfresco Community",
        "productVersion": "26.2.0",
        "cmisVersionSupported": "1.1",
    }
}


def make_response(status=200, json_data=None, content=None, reason="OK"):
    response = requests.Response()
    response.status_code = status
    response.reason = reason
    if json_data is not None:
        response._content = json.dumps(json_data).encode()
    else:
        response._content = content or b""
    return response


def cmis_object(object_id, name, base_type="cmis:folder", **properties):
    values = {
        "cmis:objectId": object_id,
        "cmis:name": name,
        "cmis:baseTypeId": base_type,
        "cmis:objectTypeId": base_type,
    }
    values.update(properties)
    return {"succinctProperties": values}


def not_found(message="Object not found"):
    return make_response(
        404, {"exception": "objectNotFound", "message": message}, reason="Not Found"
    )


class FakeSession:
    """Replay prepared responses and record the requests"""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []
        self.auth = None

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if not self.responses:
            raise AssertionError(f"Unexpected request {method} {url} {kwargs}")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response
